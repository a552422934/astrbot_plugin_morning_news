import os
import datetime
import base64
import textwrap
from io import BytesIO
from typing import Optional, Dict, Any, Tuple
from PIL import Image, ImageDraw, ImageFont
# 支持直接运行和作为模块导入
try:
    from .config import CURRENT_DIR
except ImportError:
    CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
import traceback

# --- 配置常量 ---
BASE_IMAGE_DIR = os.path.join(CURRENT_DIR, "assets")
FONT_PATH = os.path.join(BASE_IMAGE_DIR, "汉仪帅线体.ttf")  # 顶部区域字体
FONT_MSYH_PATH = os.path.join(BASE_IMAGE_DIR, "微软雅黑.ttf")  # 微软雅黑（新闻内容）
TEXT_COLOR = (0, 0, 0)  # 文本颜色 (黑色)

# --- 布局常量 ---
OUTER_MARGIN = 50  # 图片内容外边距
MARGIN_X = 50  # 内容左右边距
TOP_BAR_HEIGHT = 300  # 顶部区域高度（调大）
DATE_AREA_HEIGHT = 80  # 日期/主标题区域高度
NEWS_LINE_SPACING = 8  # 行间距
NEWS_ITEM_SPACING = 25  # 不同新闻条目之间的垂直间距
NEWS_TOP_MARGIN = 20  # 新闻列表上边距
NEWS_BOTTOM_MARGIN = 0  # 新闻列表下边距
BOTTOM_MARGIN = 50  # 底部边距
WEEKDAY_SPACING = 25  # 中英文星期之间的边距

# --- 图片尺寸常量 ---
IMAGE_WIDTH = 1000  # 图片宽度（高度动态计算）

# --- 星期几映射 ---
WEEKDAY_EN = {
    "Mon": "MONDAY",
    "Tue": "TUESDAY", 
    "Wed": "WEDNESDAY",
    "Thu": "THURSDAY",
    "Fri": "FRIDAY",
    "Sat": "SATURDAY",
    "Sun": "SUNDAY"
}

WEEKDAY_CN = {
    "Mon": "星期一",
    "Tue": "星期二",
    "Wed": "星期三", 
    "Thu": "星期四",
    "Fri": "星期五",
    "Sat": "星期六",
    "Sun": "星期日"
}

# --- 一周七天对应的颜色（RGB）---
WEEKDAY_COLORS = {
    "Mon": (43,128,235),    # 钢蓝色 - 星期一
    "Tue": (34, 139, 34),     # 绿色 - 星期二
    "Wed": (255, 140, 0),     # 橙色 - 星期三
    "Thu": (0,191,233),     # 绿色 - 星期四
    "Fri": (220, 20, 60),     # 红色 - 星期五
    "Sat": (255, 165, 0),     # 金色 - 星期六
    "Sun": (255, 69, 0),      # 橙红色 - 星期日
    "default": (70, 130, 180)  # 默认蓝色
}


def wrap_text_pixel(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    line_spacing: int,
) -> Tuple[str, int]:
    """
    根据像素宽度智能换行文本
    :return: (换行后的文本字符串, 文本块的总高度)
    """
    lines = []
    initial_words = []
    for paragraph in text.split("\n"):
        words_in_paragraph = []
        current_word = ""
        for char in paragraph:
            if "\u4e00" <= char <= "\u9fff":
                if current_word:
                    words_in_paragraph.append(current_word)
                words_in_paragraph.append(char)
                current_word = ""
            else:
                current_word += char
        if current_word:
            words_in_paragraph.append(current_word)

        processed_words = []
        for word in words_in_paragraph:
            if len(word) > 10 and not ("\u4e00" <= word[0] <= "\u9fff"):
                estimated_char_width = font.size * 0.6
                wrap_width_chars = max(1, int(max_width / estimated_char_width))
                processed_words.extend(
                    textwrap.wrap(
                        word,
                        width=wrap_width_chars,
                        break_long_words=True,
                        replace_whitespace=False,
                    )
                )
            else:
                processed_words.append(word)

        initial_words.extend(processed_words)
        initial_words.append("\n")

    if initial_words:
        initial_words.pop()

    current_line = ""
    for word in initial_words:
        if word == "\n":
            lines.append(current_line)
            current_line = ""
            continue

        separator = (
            " "
            if current_line
            and not ("\u4e00" <= word[0] <= "\u9fff")
            and not ("\u4e00" <= current_line[-1] <= "\u9fff")
            else ""
        )
        test_line = current_line + separator + word
        try:
            text_width = font.getlength(test_line)
        except AttributeError:
            bbox = draw.textbbox((0, 0), test_line, font=font)
            text_width = bbox[2] - bbox[0]

        if text_width <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
            try:
                text_width = font.getlength(current_line)
            except AttributeError:
                bbox = draw.textbbox((0, 0), current_line, font=font)
                text_width = bbox[2] - bbox[0]

            while text_width > max_width and len(current_line) > 1:
                current_line = current_line[:-1]
                try:
                    text_width = font.getlength(current_line)
                except AttributeError:
                    bbox = draw.textbbox((0, 0), current_line, font=font)
                    text_width = bbox[2] - bbox[0]

    if current_line:
        lines.append(current_line)

    final_text = "\n".join(lines)
    if not final_text:
        return "", 0

    bbox_multi = draw.multiline_textbbox(
        (0, 0), final_text, font=font, spacing=line_spacing
    )
    actual_height = bbox_multi[3] - bbox_multi[1]

    return final_text, actual_height


def get_lunar_date(date: datetime.datetime) -> str:
    """
    获取农历日期（简化版本）
    实际应用中可以使用 zhdate 等库进行准确的农历转换
    """
    lunar_months = ["正月", "二月", "三月", "四月", "五月", "六月", 
                    "七月", "八月", "九月", "十月", "冬月", "腊月"]
    lunar_days = ["初一", "初二", "初三", "初四", "初五", "初六", "初七", "初八", "初九", "初十",
                  "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十",
                  "廿一", "廿二", "廿三", "廿四", "廿五", "廿六", "廿七", "廿八", "廿九", "三十"]
    
    month_idx = (date.month - 1) % 12
    day_idx = (date.day - 1) % 30
    return f"{lunar_months[month_idx]}{lunar_days[day_idx]}"


def calculate_news_height(draw: ImageDraw.ImageDraw, news_list: list, font: ImageFont.FreeTypeFont, max_width: int) -> int:
    """
    预计算新闻列表的总高度
    """
    total_height = 0
    for i, item in enumerate(news_list):
        item = item.strip()
        numbered_item = f"{i + 1}. {item}"
        _, item_height = wrap_text_pixel(draw, numbered_item, font, max_width, NEWS_LINE_SPACING)
        total_height += item_height + NEWS_ITEM_SPACING
    return total_height


def create_news_image_from_data(news_api_data: Dict[str, Any], logger) -> Optional[str]:
    """
    根据新闻数据生成图片，高度自适应
    """
    try:
        date_str = news_api_data.get("date")
        news_list = news_api_data.get("news", [])
        tip = news_api_data.get("tip", "")

        if not date_str or not news_list:
            logger.error("[新闻图片生成] 缺少必要的新闻数据或日期")
            return None

        # 解析日期
        try:
            news_date = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            year_str = news_date.strftime("%Y年")
            month_str = news_date.strftime("%m月")
            day_str = news_date.strftime("%d日")
        except ValueError as e:
            logger.error(f"[新闻图片生成] 日期格式错误: {e}")
            return None
        
        # 从接口获取星期（优先使用接口数据）
        weekday_cn_from_api = news_api_data.get("day_of_week", "")
        if weekday_cn_from_api:
            # 接口返回中文星期，需要转换为英文缩写用于颜色映射
            cn_to_abbr = {v: k for k, v in WEEKDAY_CN.items()}
            day_of_week = cn_to_abbr.get(weekday_cn_from_api, news_date.strftime("%a"))
        else:
            day_of_week = news_date.strftime("%a")
        
        # 从接口获取农历日期
        lunar_date_str = news_api_data.get("lunar_date", "")
        if not lunar_date_str:
            lunar_date_str = get_lunar_date(news_date)

        # 检查字体文件
        if not os.path.exists(FONT_PATH):
            logger.error(f"[新闻图片生成] 字体文件缺失: {FONT_PATH}")
            return None

        # 加载字体
        try:
            # 顶部区域使用汉仪帅线体
            font_weekday_cn = ImageFont.truetype(FONT_PATH, 160)  # 中文星期（调大）
            font_weekday_en = ImageFont.truetype(FONT_PATH, 48)  # 英文星期（调大）
            font_tip = ImageFont.truetype(FONT_PATH, 24)
            font_title = ImageFont.truetype(FONT_PATH, 42)
            font_lunar = ImageFont.truetype(FONT_PATH, 24)  # 日期字体调大
            # 新闻内容使用微软雅黑
            font_news = ImageFont.truetype(FONT_MSYH_PATH, 27)
        except IOError as e:
            logger.error(f"[新闻图片生成] 加载字体文件失败: {e}")
            return None

        # 创建临时图片用于计算高度
        temp_image = Image.new("RGB", (IMAGE_WIDTH, 100), color=(255, 255, 255))
        temp_draw = ImageDraw.Draw(temp_image)
        
        # 计算新闻内容高度
        max_news_width = IMAGE_WIDTH - 2 * MARGIN_X
        news_height = calculate_news_height(temp_draw, news_list, font_news, max_news_width)
        
        # 计算总高度：外边距 + 顶部区域 + 分隔线 + 日期区域 + 分隔线 + 新闻区域（含上下边距） + 底部边距
        total_height = (OUTER_MARGIN + TOP_BAR_HEIGHT + 20 + DATE_AREA_HEIGHT + NEWS_TOP_MARGIN + news_height + NEWS_BOTTOM_MARGIN + BOTTOM_MARGIN)
        
        logger.info(f"[新闻图片生成] 动态计算图片高度: {total_height}px")

        # 创建实际图片
        image = Image.new("RGB", (IMAGE_WIDTH, total_height), color=(255, 255, 255))
        draw = ImageDraw.Draw(image)
        width = IMAGE_WIDTH

        # ========== 绘制顶部区域（纯色背景）==========
        top_color = WEEKDAY_COLORS.get(day_of_week, WEEKDAY_COLORS["default"])
        draw.rectangle(
            [(OUTER_MARGIN, OUTER_MARGIN), (width - OUTER_MARGIN, OUTER_MARGIN + TOP_BAR_HEIGHT)],
            fill=top_color,
            outline=None
        )
        
        # 获取星期几的中英文
        weekday_en = WEEKDAY_EN.get(day_of_week, "MONDAY")
        weekday_cn = WEEKDAY_CN.get(day_of_week, "星期一")
        tip_text = tip.strip() if tip else "今日无一言"
        
        content_x = OUTER_MARGIN
        content_width = width - 2 * OUTER_MARGIN
        
        # 绘制中文星期（居中）
        weekday_cn_bbox = draw.textbbox((0, 0), weekday_cn, font=font_weekday_cn)
        weekday_cn_width = weekday_cn_bbox[2] - weekday_cn_bbox[0]
        weekday_cn_height = weekday_cn_bbox[3] - weekday_cn_bbox[1]
        weekday_cn_x = content_x + (content_width - weekday_cn_width) // 2
        weekday_cn_y = OUTER_MARGIN + 30
        draw.text((weekday_cn_x, weekday_cn_y), weekday_cn, fill=(255, 255, 255), font=font_weekday_cn)
        
        # 绘制英文星期（居中）
        weekday_en_bbox = draw.textbbox((0, 0), weekday_en, font=font_weekday_en)
        weekday_en_width = weekday_en_bbox[2] - weekday_en_bbox[0]
        weekday_en_x = content_x + (content_width - weekday_en_width) // 2
        weekday_en_y = weekday_cn_y + weekday_cn_height + WEEKDAY_SPACING  # 精确控制边距
        draw.text((weekday_en_x, weekday_en_y), weekday_en, fill=(255, 255, 255), font=font_weekday_en)
        
        # 绘制"一言"（底部居中）
        max_tip_width = content_width - 40
        wrapped_tip, _ = wrap_text_pixel(draw, tip_text, font_tip, max_tip_width, 6)
        tip_bbox = draw.multiline_textbbox((0, 0), wrapped_tip, font=font_tip, spacing=6)
        tip_height = tip_bbox[3] - tip_bbox[1]
        tip_width = tip_bbox[2] - tip_bbox[0]
        tip_x = content_x + (content_width - tip_width) // 2
        tip_y = OUTER_MARGIN + TOP_BAR_HEIGHT - tip_height - 20
        draw.text((tip_x, tip_y), wrapped_tip, fill=(255, 255, 255), font=font_tip, spacing=6)
        
        # ========== 绘制分隔线 ==========
        separator_y = OUTER_MARGIN + TOP_BAR_HEIGHT
        draw.line(
            [(OUTER_MARGIN, separator_y), (width - OUTER_MARGIN, separator_y)],
            fill=(0, 0, 0),
            width=2
        )

        # ========== 绘制日期/主标题区域（上下居中）==========
        date_area_start_y = separator_y
        date_area_end_y = separator_y + DATE_AREA_HEIGHT
        date_area_center_y = (date_area_start_y + date_area_end_y) // 2
        
        # 解析农历日期
        if "年" in lunar_date_str:
            lunar_parts = lunar_date_str.split("年")
            lunar_date_display = lunar_parts[1] if len(lunar_parts) > 1 else lunar_date_str
        else:
            lunar_date_display = lunar_date_str
        
        # 左侧：农历（上下居中，左对齐）
        lunar_text = lunar_date_str  # 直接使用完整农历，如"乙巳年十一月廿七"
        lunar_bbox = draw.textbbox((0, 0), lunar_text, font=font_lunar)
        lunar_height = lunar_bbox[3] - lunar_bbox[1]
        lunar_y = date_area_center_y - lunar_height // 2
        draw.text((MARGIN_X, lunar_y), lunar_text, fill=TEXT_COLOR, font=font_lunar)
        
        # 中间：主标题（上下居中）
        title_text = "每日60秒读懂世界"
        title_bbox = draw.textbbox((0, 0), title_text, font=font_title)
        title_width = title_bbox[2] - title_bbox[0]
        title_height = title_bbox[3] - title_bbox[1]
        title_x = (width - title_width) // 2
        title_y = date_area_center_y - title_height // 2
        draw.text((title_x, title_y), title_text, fill=(220, 20, 60), font=font_title)
        
        # 右侧：公历（上下居中，左对齐显示）
        gregorian_text = f"{year_str}{month_str}{day_str}"
        gregorian_bbox = draw.textbbox((0, 0), gregorian_text, font=font_lunar)
        gregorian_width = gregorian_bbox[2] - gregorian_bbox[0]
        gregorian_height = gregorian_bbox[3] - gregorian_bbox[1]
        gregorian_x = width - gregorian_width - MARGIN_X
        gregorian_y = date_area_center_y - gregorian_height // 2
        draw.text((gregorian_x, gregorian_y), gregorian_text, fill=TEXT_COLOR, font=font_lunar)
        
        # ========== 绘制分隔线 ==========
        separator_y2 = date_area_end_y
        draw.line(
            [(OUTER_MARGIN, separator_y2), (width - OUTER_MARGIN, separator_y2)],
            fill=(0, 0, 0),
            width=2
        )

        # ========== 绘制新闻列表 ==========
        current_y = separator_y2 + NEWS_TOP_MARGIN  # 使用上边距常量

        for i, item in enumerate(news_list):
            item = item.strip()
            numbered_item = f"{i + 1}. {item}"

            wrapped_item, _ = wrap_text_pixel(
                draw, numbered_item, font_news, max_news_width, NEWS_LINE_SPACING
            )

            if not wrapped_item:
                continue

            draw.text(
                (MARGIN_X, current_y),
                wrapped_item,
                fill=TEXT_COLOR,
                font=font_news,
                spacing=NEWS_LINE_SPACING,
            )

            item_bbox = draw.multiline_textbbox(
                (MARGIN_X, current_y),
                wrapped_item,
                font=font_news,
                spacing=NEWS_LINE_SPACING,
            )
            item_height = item_bbox[3] - item_bbox[1]
            current_y += item_height + NEWS_ITEM_SPACING

        # 转换为 Base64 编码
        img_byte_arr = BytesIO()
        image.save(img_byte_arr, format="PNG", quality=88)
        img_bytes = img_byte_arr.getvalue()

        base64_data = base64.b64encode(img_bytes).decode("utf-8")
        logger.info("[新闻图片生成] 新闻图片生成成功")
        return base64_data

    except FileNotFoundError as e:
        logger.error(f"[新闻图片生成] 文件未找到: {e}")
        return None
    except Exception as e:
        logger.error(f"[新闻图片生成] 未知错误: {e}")
        traceback.print_exc()
        return None


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger("news_image_generator")

    # 示例数据
    example_api_data = {
        "date": "2026-01-15",
        "news": [
            "2025 年我国进出口总值首破 45 万亿元，创历史新高，继续保持全球货物贸易第一大国地位",
            "央行 1 月 15 日将开展 9000 亿元 6 月期买断式逆回购操作，为连续第 8 个月加量续作",
            "2025 年超 1.1 万家银行线下网点关闭，同期新设网点超 8400 家，全年网点净减少逾 2000 家",
            "三部门：换房退个税政策延期至 2027 年底，纳税人出售现住房后 1 年内重购住房可享退税优惠",
            "南京再次放宽落户门槛：45 岁以下本科毕业可直接落户，三级及以上职业技能人员可直接落户",
            "前程无忧报告：2025 年员工整体离职率降至 14.8%，已连续 3 年小幅走低",
            "吉林长白山婚姻登记处上线：领证情侣终身免门票游长白山景区",
            "多地快递驿站转让帖在线上涌现：经营者称每天工作十几个小时，每月只赚五六千",
            "U23 亚洲杯：中国 0 比 0 战平泰国，首次以小组赛不败战绩晋级淘汰赛",
            "数据显示：2025 年全球短剧应用内购收入超 28 亿美元，同比涨幅达 116%",
            "阿根廷 2025 年通胀率降至近 8 年最低水平；阿根廷总统米莱称计划今年访问中国",
            "泰媒：泰国一在建铁路起重机倒塌砸中行驶火车，已致 32 死 67 伤，涉事标段无中企参与",
            "外媒：美国即将正式退出世卫组织，以色列宣布跟随美国退群，世卫组织谭德塞称此举威胁全球安全",
            "美媒：美国将暂停对俄罗斯、巴西、泰国等 75 国所有签证，以打击潜在公共负担申请人",
            "外媒：丹麦军方开始向格陵兰岛增派力量；法国将在格陵兰岛开设领事馆"
        ],
        "tip": "如果你曾经把失败当成清醒剂，就千万别让成功变成迷魂汤",
        "lunar_date": "乙巳年十一月廿七"
    }

    logger.info("[测试] 开始生成新闻图片...")
    image_base64 = create_news_image_from_data(example_api_data, logger)

    if image_base64:
        try:
            output_filename = "generated_news_test.jpg"
            with open(output_filename, "wb") as f:
                f.write(base64.b64decode(image_base64))
            logger.info(f"[测试] 新闻图片生成成功，已保存为 {output_filename}")
        except Exception as e:
            logger.error(f"[测试] 保存图片时发生错误: {e}")
    else:
        logger.error("[测试] 新闻图片生成失败")
