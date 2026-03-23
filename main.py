import asyncio
import aiohttp
import datetime
import base64
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.core.message.message_event_result import MessageChain
from astrbot.api.message_components import Plain, Image
from .news_image_generator import create_news_image_from_data


@register(
    "astrbot_plugin_daily_news",
    "anka",
    "anka - 每日60s早报推送插件, 请先设置推送目标和时间, 详情见github页面!",
    "2.1.0",
)
class DailyNewsPlugin(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config

        # 用于在消息发送阶段做串行化，避免同一时间多处逻辑并发 send_message 造成混乱
        self._send_lock = asyncio.Lock()

        # 定时任务在 __init__ 启动可能遇到“无运行中的事件循环”风险，因此延迟启动
        self._daily_task = None
        self._task_start_requested = False
        
        # 清理和验证群组ID
        raw_groups = config.get("target_groups", [])
        self.target_groups = []
        for group_id in raw_groups:
            if isinstance(group_id, str):
                cleaned_id = group_id.strip()
                if cleaned_id:
                    # 验证格式
                    parts = cleaned_id.split(":")
                    if len(parts) == 3:
                        self.target_groups.append(cleaned_id)
                        logger.info(f"[每日早报] 有效的群组ID: {cleaned_id}")
                    else:
                        logger.warning(f"[每日早报] 群组ID格式错误，已跳过: {group_id} (应为 '前缀:中缀:后缀')")
                else:
                    logger.warning(f"[每日早报] 群组ID为空，已跳过")
            else:
                logger.warning(f"[每日早报] 群组ID类型错误，已跳过: {group_id} (类型: {type(group_id).__name__})")
        
        self.push_time = self._normalize_push_time(config.get("push_time", "08:00"))
        self.push_hour, self.push_minute = self._parse_push_time_to_hm(self.push_time)
        self.show_text_news = config.get("show_text_news", False)
        self.use_local_image_draw = config.get("use_local_image_draw", True)

        # 记录配置信息
        logger.info(f"[每日早报] 插件初始化完成")
        logger.info(f"[每日早报] 原始目标群组: {raw_groups}")
        logger.info(f"[每日早报] 清理后目标群组: {self.target_groups}")
        logger.info(f"[每日早报] 推送时间: {self.push_time}")
        logger.info(f"[每日早报] 显示文本早报: {self.show_text_news}")
        logger.info(f"[每日早报] 使用本地图片绘制: {self.use_local_image_draw}")

        # 启动定时任务（如果当前没有运行中的事件循环，则延迟到首次命令触发）
        self._start_daily_task_if_possible()

    def _normalize_push_time(self, raw_value) -> str:
        """把 push_time 规范化成 'HH:MM'，非法配置回退默认值并避免 ValueError"""
        default = "08:00"
        try:
            if not isinstance(raw_value, str):
                raise ValueError("push_time must be a string")
            value = raw_value.strip()
            parts = value.split(":")
            if len(parts) != 2:
                raise ValueError("push_time format invalid")
            hour = int(parts[0])
            minute = int(parts[1])
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError("hour/minute out of range")
            return f"{hour:02d}:{minute:02d}"
        except Exception as e:
            logger.warning(f"[每日早报] push_time 配置非法: {raw_value}，已回退默认值 {default}，原因: {e}")
            return default

    def _parse_push_time_to_hm(self, normalized_push_time: str) -> tuple[int, int]:
        """输入保证为 'HH:MM' 格式，因此该函数不再做额外容错"""
        hour_str, minute_str = normalized_push_time.split(":")
        return int(hour_str), int(minute_str)

    def _start_daily_task_if_possible(self) -> None:
        if self._daily_task is not None and not self._daily_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
            self._daily_task = loop.create_task(self.daily_task())
            logger.info("[每日早报] 定时任务已创建")
        except RuntimeError:
            # 未进入运行中的事件循环，延迟到后续命令触发时再启动
            self._task_start_requested = True
            logger.warning("[每日早报] 当前未发现运行中的事件循环，定时任务将延迟启动")

    def _ensure_daily_task_started(self) -> None:
        if self._task_start_requested:
            self._start_daily_task_if_possible()
            self._task_start_requested = False

    def _build_image_chain(self, image_data: str) -> MessageChain:
        image_message_chain = MessageChain()
        image_message_chain.chain = [Image.fromBase64(image_data)]
        return image_message_chain

    def _build_text_chain(self, text: str) -> MessageChain:
        text_message_chain = MessageChain()
        text_message_chain.chain = [Plain(text)]
        return text_message_chain

    async def _send_message_safely(self, origin: str, message_chain: MessageChain):
        """统一 send_message 调用入口，控制并发与异常日志收敛"""
        async with self._send_lock:
            return await self.context.send_message(origin, message_chain)

    def _extract_news_payload(self, raw_json):
        """
        把不同 API 可能返回的结构归一化为：{date: str, news: List[str], tip: str}
        返回 None 表示无法解析
        """
        try:
            if not isinstance(raw_json, dict):
                return None

            candidate = raw_json.get("data", raw_json)
            if not isinstance(candidate, dict):
                return None

            date_str = candidate.get("date") or ""
            news_items = candidate.get("news", [])
            tip = candidate.get("tip") or ""
            image_url = candidate.get("image")  # 仅当配置 use_local_image_draw=false 时需要

            # 可选字段：用于提升图片绘制的准确性
            weekday_cn = candidate.get("day_of_week")
            lunar_date = candidate.get("lunar_date")

            if isinstance(news_items, str):
                news_items = [x for x in news_items.splitlines() if x.strip()]
            if not isinstance(news_items, (list, tuple)):
                news_items = []

            normalized_news = []
            for item in news_items:
                if item is None:
                    continue
                s = str(item).strip()
                if s:
                    normalized_news.append(s)

            # date 与 news 都是必要字段；tip 允许为空
            if not date_str or not normalized_news:
                return None

            payload = {"date": str(date_str), "news": normalized_news, "tip": str(tip)}
            if image_url:
                payload["image"] = str(image_url)
            if weekday_cn:
                payload["day_of_week"] = str(weekday_cn)
            if lunar_date:
                payload["lunar_date"] = str(lunar_date)
            return payload
        except Exception as e:
            logger.warning(f"[每日早报] 解析早报数据结构失败: {e}")
            return None

    # 获取60s早报数据
    async def fetch_news_data(self):
        """获取每日60s早报数据

        :return: 早报数据
        :rtype: dict
        """
        urls = [
            "https://60s.viki.moe/v2/60s",
            "https://60s.b23.run/v2/60s",
            "https://60s-api-cf.viki.moe/v2/60s",
            "https://60s-api.114128.xyz/v2/60s",
            "https://60s-api-cf.114128.xyz/v2/60s"
        ]

        timeout = aiohttp.ClientTimeout(total=12, connect=5, sock_read=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for url in urls:
                try:
                    async with session.get(url) as response:
                        if response.status == 200:
                            raw_json = await response.json(content_type=None)
                            payload = self._extract_news_payload(raw_json)
                            if payload:
                                return payload
                            logger.warning(f"[每日早报] API返回结构异常，已跳过: {url}")
                        else:
                            logger.warning(f"API返回错误代码: {response.status}")
                except Exception as e:
                    logger.warning(f"[每日早报] 从 {url} 获取数据时出错: {e}")
                    continue
        
        # 所有URL都失败时返回None
        logger.error("[每日早报] 所有早报API都失败，无法获取数据")
        return None

    # 下载60s早报图片
    async def download_image(self, news_data):
        """下载每日60s图片

        :param news_data: 早报数据
        :return: 图片的base64编码
        :rtype: str
        """
        try:
            image_url = news_data.get("image")
            if not image_url:
                raise ValueError("news_data 缺少 image 字段")
            logger.info(f"[每日早报] 从URL下载图片: {image_url}")

            async with aiohttp.ClientSession() as session:
                timeout = aiohttp.ClientTimeout(total=30)
                async with session.get(image_url, timeout=timeout) as response:
                    if response.status != 200:
                        raise Exception(f"下载图片失败，状态码: {response.status}")
                    image_data = await response.read()
                    logger.info(f"[每日早报] 图片下载成功, 大小: {len(image_data)}字节")
                    base64_data = base64.b64encode(image_data).decode("utf-8")
                    return base64_data
        except Exception as e:
            logger.error(f"[每日早报] 下载图片时出错: {e}")
            logger.exception("[每日早报] 下载图片时异常")
            raise

    # 生成早报文本
    def generate_news_text(self, news_data):
        """生成早报文本

        :param news_data: 早报数据
        :return: 早报文本
        :rtype: str
        """
        date = str(news_data.get("date", "") or "")
        news_items = news_data.get("news", []) or []
        tip = str(news_data.get("tip", "") or "")

        if not isinstance(news_items, (list, tuple)):
            news_items = [str(news_items)]

        text = f"【每日60秒早报】{date}\n\n"
        for i, item in enumerate(news_items, 1):
            s = str(item).strip()
            if not s:
                continue
            text += f"{i}. {s}\n"

        text += f"\n【今日提示】{tip}\n"
        text += f"数据来源: 每日60秒早报"

        return text

    # 向指定群组推送60s早报
    async def send_daily_news(self):
        """向所有目标群组推送每日早报"""
        try:
            logger.info("[每日早报] 开始获取早报数据...")
            news_data = await self.fetch_news_data()
            if not news_data:
                logger.error("[每日早报] 获取早报数据失败，返回数据为空")
                return
            logger.debug(f"[每日早报] 获取到的早报数据: {news_data}")
            
            logger.info(f"[每日早报] 开始生成图片，使用本地绘制: {self.use_local_image_draw}")
            image_data = None
            if self.use_local_image_draw:
                image_data = create_news_image_from_data(news_data, logger)
                if not image_data:
                    logger.error("[每日早报] 图片生成失败，可能是字体文件缺失，请检查 assets 目录中的字体文件")
            else:
                image_data = await self.download_image(news_data)
            if image_data:
                logger.debug(
                    f"[图片生成] 生成的图片 Base64 数据前 100 字符: {image_data[:100]}"
                )

            if image_data:
                logger.info("[每日早报] 图片生成成功")

            if not self.target_groups:
                logger.warning("[每日早报] 未配置目标群组，无法推送")
                return

            logger.info(
                f"[每日早报] 准备向 {len(self.target_groups)} 个群组推送每日早报: {self.target_groups}"
            )

            success_count = 0
            for group_id in self.target_groups:
                try:
                    # 群组ID已在初始化时清理和验证，这里直接使用
                    logger.info(f"[每日早报] 处理群组: {group_id}")
                    
                    # 再次验证（双重保险）
                    if not group_id or not isinstance(group_id, str):
                        logger.error(f"[每日早报] 群组ID无效: {group_id}")
                        continue
                    
                    # 检查群组ID格式
                    parts = group_id.split(":")
                    if len(parts) != 3:
                        logger.error(f"[每日早报] 群组ID格式错误，应为 '前缀:中缀:后缀'，实际: {group_id}")
                        continue
                    
                    logger.info(f"[每日早报] 群组ID解析: 前缀={parts[0]}, 中缀={parts[1]}, 后缀={parts[2]}")
                    
                    send_any = False

                    # 先发送图片（如果生成成功）
                    if image_data:
                        logger.debug(f"[每日早报] 图片Base64长度: {len(image_data)} 字符")
                        logger.debug(f"[每日早报] 图片Base64前50字符: {image_data[:50]}")
                        image_message_chain = self._build_image_chain(image_data)
                        logger.info(f"[每日早报] 正在向群组 {group_id} 发送图片...")
                        try:
                            result = await self._send_message_safely(group_id, image_message_chain)
                            logger.info(f"[每日早报] send_message 返回结果: {result} (类型: {type(result).__name__})")
                            if result is not False and result is not None:
                                send_any = True
                                logger.info(f"[每日早报] 图片已成功发送到群组 {group_id}")
                            else:
                                logger.error(f"[每日早报] 图片发送失败，返回值为: {result}")
                        except Exception:
                            logger.exception(f"[每日早报] 图片发送失败，群组: {group_id}")

                    # 再发送文本（按配置）
                    if self.show_text_news:
                        text_news = self.generate_news_text(news_data)
                        text_message_chain = self._build_text_chain(text_news)
                        logger.info(f"[每日早报] 正在向群组 {group_id} 发送文本...")
                        try:
                            result = await self._send_message_safely(group_id, text_message_chain)
                            logger.info(f"[每日早报] 文本send_message 返回结果: {result}")
                            if result is not False and result is not None:
                                send_any = True
                                logger.info(f"[每日早报] 文本已成功发送到群组 {group_id}")
                            else:
                                logger.warning(f"[每日早报] 文本发送失败，返回值为: {result}")
                        except Exception:
                            logger.exception(f"[每日早报] 文本发送失败，群组: {group_id}")

                    if send_any:
                        logger.info(f"[每日早报] 已成功向群 {group_id} 推送每日早报")
                        success_count += 1
                    await asyncio.sleep(1)
                except Exception as e:
                    logger.error(f"[每日早报] 向群组 {group_id} 推送消息时出错: {e}")
                    logger.error(f"[每日早报] 错误类型: {type(e).__name__}")
                    logger.exception(f"[每日早报] 群组推送异常，群组: {group_id}")
            
            logger.info(f"[每日早报] 推送完成，成功: {success_count}/{len(self.target_groups)}")
        except Exception as e:
            logger.error(f"[每日早报] 推送每日早报时出错: {e}")
            logger.error(f"[每日早报] 错误类型: {type(e).__name__}")
            logger.exception("[每日早报] 推送每日早报时异常")

    # 计算到明天指定时间的秒数
    def calculate_sleep_time(self):
        """计算到下一次推送时间的秒数"""
        now = datetime.datetime.now()
        target_time = now.replace(hour=self.push_hour, minute=self.push_minute, second=0, microsecond=0)
        # 如果目标时间已经过了，则设置为明天
        if target_time <= now:
            target_time += datetime.timedelta(days=1)

        seconds = (target_time - now).total_seconds()
        logger.debug(f"[每日早报] 当前时间: {now.strftime('%Y-%m-%d %H:%M:%S')}, 目标时间: {target_time.strftime('%Y-%m-%d %H:%M:%S')}, 等待秒数: {seconds}")
        return seconds

    # 定时任务
    async def daily_task(self):
        """定时推送任务"""
        logger.info("[每日早报] 定时任务开始运行")
        task_loop_count = 0
        while True:
            try:
                task_loop_count += 1
                logger.info(f"[每日早报] 定时任务循环 #{task_loop_count} 开始")
                
                # 检查配置
                if not self.target_groups:
                    logger.warning("[每日早报] 目标群组为空，等待配置...")
                    await asyncio.sleep(300)  # 等待5分钟后重试
                    continue
                
                # 计算到下次推送的时间
                try:
                    sleep_time = self.calculate_sleep_time()
                except Exception as e:
                    logger.error(f"[每日早报] 计算 sleep_time 失败: {e}，将延迟重试")
                    await asyncio.sleep(300)
                    continue
                hours = int(sleep_time / 3600)
                minutes = int((sleep_time % 3600) / 60)
                seconds = int(sleep_time % 60)
                logger.info(f"[每日早报] 定时任务已启动，下次推送将在 {hours}小时{minutes}分钟{seconds}秒后 ({self.push_time})")

                # 使用分段等待，避免长时间 sleep 不准确
                # 如果等待时间超过1小时，每5分钟检查一次
                if sleep_time > 3600:
                    # 长时间等待，分段进行
                    remaining = sleep_time
                    check_interval = 300  # 每5分钟检查一次
                    while remaining > check_interval:
                        logger.debug(f"[每日早报] 等待中，剩余 {int(remaining/60)} 分钟...")
                        await asyncio.sleep(check_interval)
                        remaining -= check_interval
                        # 重新计算剩余时间，避免时间漂移
                        remaining = self.calculate_sleep_time()
                    # 等待剩余时间
                    if remaining > 0:
                        logger.info(f"[每日早报] 最后等待 {int(remaining)} 秒...")
                        await asyncio.sleep(remaining)
                else:
                    # 短时间等待，直接 sleep
                    logger.info(f"[每日早报] 开始等待 {sleep_time} 秒 ({hours}小时{minutes}分钟{seconds}秒)...")
                    await asyncio.sleep(sleep_time)
                
                # 验证是否到达推送时间
                now = datetime.datetime.now()
                target_hour, target_minute = self.push_hour, self.push_minute
                current_hour = now.hour
                current_minute = now.minute
                
                logger.info(f"[每日早报] 等待完成，当前时间: {now.strftime('%H:%M:%S')}, 目标时间: {self.push_time}")
                
                # 检查是否到达推送时间（允许1分钟误差）
                time_diff = abs((current_hour * 60 + current_minute) - (target_hour * 60 + target_minute))
                if time_diff > 1:
                    logger.warning(f"[每日早报] 时间差异较大: {time_diff} 分钟，可能 sleep 不准确，继续执行推送")

                # 推送早报
                logger.info(f"[每日早报] 定时推送触发，开始推送早报...")
                try:
                    await self.send_daily_news()
                    logger.info(f"[每日早报] 定时推送完成")
                except Exception as send_error:
                    logger.error(f"[每日早报] 推送过程中出错: {send_error}")
                    logger.error(f"[每日早报] 推送错误类型: {type(send_error).__name__}")
                    logger.exception("[每日早报] 推送过程中异常")
                    # 推送失败不影响下次定时，继续循环

                # 推送完成后，立即重新计算下次推送时间（不等待60秒）
                logger.info("[每日早报] 推送完成，立即重新计算下次推送时间...")
                # 不等待，直接进入下一轮循环
                
            except asyncio.CancelledError:
                # 任务被取消，重新抛出异常
                logger.info("[每日早报] 定时任务被取消")
                raise
            except Exception as e:
                logger.error(f"[每日早报] 定时任务出错: {e}")
                logger.error(f"[每日早报] 错误类型: {type(e).__name__}")
                logger.exception("[每日早报] 定时任务异常")
                # 出错后等待5分钟再重试
                logger.info("[每日早报] 等待300秒后重试...")
                await asyncio.sleep(300)

    @filter.command("get_status", alias={'获取状态', 'status', '状态'})
    async def check_status(self, event: AstrMessageEvent):
        """检查插件状态"""
        self._ensure_daily_task_started()
        now = datetime.datetime.now()
        try:
            sleep_time = self.calculate_sleep_time()
        except Exception:
            sleep_time = 0
        hours = int(sleep_time / 3600)
        minutes = int((sleep_time % 3600) / 60)
        
        # 检查定时任务状态
        task_running = bool(self._daily_task) and (not self._daily_task.done())
        task_cancelled = bool(self._daily_task) and self._daily_task.cancelled()
        
        status_msg = (
            f"每日60s早报插件状态\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"目标群组: {', '.join(map(str, self.target_groups)) if self.target_groups else '未配置'}\n"
            f"推送时间: {self.push_time}\n"
            f"文本早报显示: {'开启' if self.show_text_news else '关闭'}\n"
            f"使用本地图片绘制: {'是' if self.use_local_image_draw else '否'}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"定时任务状态: {'运行中' if task_running else '已停止'}\n"
            f"定时任务已取消: {'是' if task_cancelled else '否'}\n"
            f"当前时间: {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"距离下次推送: {hours}小时{minutes}分钟\n"
        )
        
        if not self.target_groups:
            status_msg += "\n⚠️ 警告: 未配置目标群组，定时推送无法工作！"
        if not task_running:
            status_msg += "\n⚠️ 警告: 定时任务未运行，请重启插件！"

        yield event.plain_result(status_msg)

    @filter.command("get_config", alias={'获取配置', 'config', '配置', '群组配置'})
    async def get_config(self, event: AstrMessageEvent):
        """获取当前群组的正确配置"""
        try:
            self._ensure_daily_task_started()
            current_origin = event.unified_msg_origin
            logger.info(f"[获取群组ID] 当前消息来源: {current_origin}")
            
            # 解析当前消息来源
            parts = current_origin.split(":")
            if len(parts) == 3:
                prefix, middle, suffix = parts
                help_msg = (
                    f"完整配置格式:\n"
                    f"请在插件配置唯一标识符中使用以下格式:\n"
                    f"{current_origin}\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"配置格式: \n"
                    f"前缀: {prefix}\n"
                    f"中缀: {middle}\n"
                    f"后缀: {suffix}\n"
                )
            else:
                help_msg = (
                    f"当前消息来源格式异常: {current_origin}\n"
                    f"无法解析为 '前缀:中缀:后缀' 格式"
                )
            
            yield event.plain_result(help_msg)
        except Exception as e:
            logger.error(f"[获取群组ID] 出错: {e}")
            logger.exception("[获取群组ID] 异常")
            yield event.plain_result(f"获取失败: {str(e)}")
        finally:
            event.stop_event()


    @filter.command("send_test", alias={'测试', 'test', '测试发送', '发送测试','测试推送'})
    async def send_test(self, event: AstrMessageEvent):
        """测试向配置的群组发送今日早报图片"""
        try:
            self._ensure_daily_task_started()
            if not self.target_groups:
                yield event.plain_result("❌ 未配置目标群组")
                return
            
            # 先获取早报数据
            logger.info("[测试] 开始获取今日早报数据...")
            news_data = await self.fetch_news_data()
            if not news_data:
                yield event.plain_result("❌ 获取早报数据失败")
                return
            
            # 生成或下载图片
            logger.info("[测试] 开始生成/下载早报图片...")
            if not self.use_local_image_draw:
                image_data = await self.download_image(news_data)
            else:
                image_data = create_news_image_from_data(news_data, logger)
            
            if not image_data:
                yield event.plain_result("❌ 图片生成/下载失败")
                return
            
            # 向各个群组发送早报图片
            test_results = []
            for group_id in self.target_groups:
                try:
                    # 清理群组ID（去除前后空格）
                    original_group_id = group_id
                    group_id = group_id.strip() if isinstance(group_id, str) else str(group_id).strip()
                    
                    if original_group_id != group_id:
                        logger.warning(f"[测试] 群组ID有空格，已清理: '{original_group_id}' -> '{group_id}'")
                    
                    # 验证群组ID格式
                    logger.info(f"[测试] 原始群组ID: '{original_group_id}'")
                    logger.info(f"[测试] 清理后群组ID: '{group_id}'")
                    
                    # 检查群组ID格式
                    parts = group_id.split(":")
                    if len(parts) != 3:
                        logger.error(f"[测试] 群组ID格式错误，应为 '前缀:中缀:后缀'，实际: {group_id}")
                        test_results.append(f"❌ {group_id}: 格式错误 (应为 '前缀:中缀:后缀')")
                        continue
                    
                    logger.info(f"[测试] 群组ID解析: 前缀={parts[0]}, 中缀={parts[1]}, 后缀={parts[2]}")
                    
                    # 发送今日早报图片
                    logger.info(f"[测试] 正在向群组 {group_id} 发送今日早报图片...")
                    image_message_chain = MessageChain()
                    image_message = [Image.fromBase64(image_data)]
                    image_message_chain.chain = image_message
                    
                    result = await self.context.send_message(group_id, image_message_chain)
                    logger.info(f"[测试] send_message 返回结果: {result} (类型: {type(result).__name__})")
                    
                    # 检查返回值，False 或 None 表示发送失败
                    if result is False or result is None:
                        logger.warning(f"[测试] 发送失败，返回值为: {result}")
                        logger.warning(f"[测试] 可能的原因:")
                        logger.warning(f"[测试]   1. 群组ID无效或不存在")
                        logger.warning(f"[测试]   2. 机器人没有在该群组的发送权限")
                        logger.warning(f"[测试]   3. 平台连接问题 (前缀: {parts[0]})")
                        logger.warning(f"[测试]   4. 群组不存在或机器人不在群组中")
                        test_results.append(f"❌ {group_id}: 失败 (返回: {result})\n   可能原因: 群组ID无效/权限不足/平台连接问题")
                    else:
                        logger.info(f"[测试] 发送成功")
                        test_results.append(f"✅ {group_id}: 成功 (返回: {result})")
                    
                    await asyncio.sleep(1)  # 避免发送过快
                except Exception as e:
                    logger.error(f"[测试] 向群组 {group_id} 发送失败: {e}")
                    logger.error(f"[测试] 错误类型: {type(e).__name__}")
                    logger.exception(f"[测试] 发送失败，群组: {group_id}")
                    test_results.append(f"❌ {group_id}: 异常 ({str(e)})")
            
            result_msg = "测试结果:" + "\n".join(test_results)
            yield event.plain_result(result_msg)

        except Exception as e:
            logger.error(f"[测试] 测试发送出错: {e}")
            logger.exception("[测试] 测试发送出错")
            yield event.plain_result(f"测试失败: {str(e)}")
        finally:
            event.stop_event()



    @filter.command("get_news", alias={'早报', 'news', '获取早报', '今日早报', '60秒早报','60s'})
    async def manual_get_news(self, event: AstrMessageEvent, mode: str = "all"):
        """手动获取今日早报

        Args:
            mode: 获取模式，可选值: image(仅图片)/text(仅文本)/all(图片+文本)
        """
        try:
            self._ensure_daily_task_started()

            mode = (mode or "all").strip().lower()
            if mode not in {"image", "text", "all"}:
                yield event.plain_result("❌ 模式参数非法，可选: image/text/all")
                return

            send_image = mode in {"image", "all"}
            send_text = mode in {"text", "all"}

            logger.info(f"[每日早报] 手动获取早报，模式: {mode}")

            logger.info(f"[每日早报] 手动获取早报，模式: {mode}")
            try:
                news_data = await self.fetch_news_data()
                logger.debug(f"[每日早报] 获取到的早报数据: {news_data}")
                if not news_data:
                    yield event.plain_result("❌ 获取早报数据失败")
                    return

                origin = event.unified_msg_origin
                image_data = None

                if send_image:
                    # 生成/下载图片（失败不影响文本发送）
                    if not self.use_local_image_draw:
                        image_data = await self.download_image(news_data)
                    else:
                        image_data = create_news_image_from_data(news_data, logger)

                    if not image_data:
                        logger.error("[每日早报] 图片生成失败")
                        yield event.plain_result("⚠️ 图片生成失败，请检查字体文件是否存在于 assets 目录中")

                    if image_data:
                        logger.debug(f"[图片生成] 生成的图片 Base64 数据前 100 字符: {image_data[:100]}")

                # 发送图片
                if send_image and image_data:
                    image_message_chain = self._build_image_chain(image_data)
                    logger.info(f"[每日早报] 向 {origin} 发送图片")
                    try:
                        await self._send_message_safely(origin, image_message_chain)
                    except Exception:
                        logger.exception(f"[每日早报] 向 {origin} 发送图片失败")

                # 发送文本
                if send_text:
                    text_news = self.generate_news_text(news_data)
                    text_message_chain = self._build_text_chain(text_news)
                    logger.info(f"[每日早报] 向 {origin} 发送文本")
                    try:
                        await self._send_message_safely(origin, text_message_chain)
                    except Exception:
                        logger.exception(f"[每日早报] 向 {origin} 发送文本失败")

                logger.info(f"[每日早报] 已向 {origin} 发送每日早报（模式: {mode}）")
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"[每日早报] 发送每日早报时出错: {e}")
                logger.exception("[每日早报] 发送每日早报异常")

        except Exception as e:
            logger.error(f"[每日早报] 手动获取早报时出错: {e}")
            logger.exception("[每日早报] 手动获取早报异常")
            yield event.plain_result(f"获取早报失败: {str(e)}")
        finally:
            event.stop_event()

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        if self._daily_task is None:
            return
        self._daily_task.cancel()
        try:
            await self._daily_task
        except asyncio.CancelledError:
            logger.info("[每日早报] 定时任务已取消并退出")
        except Exception:
            logger.exception("[每日早报] terminate 时捕获到异常")
