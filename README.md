# 📰 AstrBot Morning News

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT) ![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue) ![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey) [![PRs Welcome](https://img.shields.io/badge/PRs-Welcome-brightgreen)](CONTRIBUTING.md)

每日早报推送插件 - 自动推送每日热点新闻，让你的群聊成员快速了解全球大事！

## 📝 使用教程

​ 1.在需要推送的群里发送`/get_config`，获取群组唯一标识符

​ 2.在插件配置：输入群组唯一标识符列表，设置推送时间

​ 3.在群里发送`/test_send`，测试是否成功

## ✨ 功能特性

- 🕒 支持每日定时推送
- 📊 图文并茂，内容丰富
- 🔄 支持手动获取、推送今日早报
- 🎯 支持多群组推送
- 📱 同时支持图片与文字模式
- 🌐 数据源可靠稳定
- 🎨 支持本地绘制每日早报图片

## 💡 常见问题

为什么修改配置后插件不生效？

- 请确保在修改配置后重启插件以使更改生效(默认自动重启)。

## 🛠️ 配置说明

在插件配置中设置以下参数:

```json
{
  "target_groups": {
    "description": "需要推送早报群组唯一标识符列表",
    "type": "list",
    "hint": "填写需要接收60s早报推送的群组唯一标识符，
    如: 你的机器人名称(自己起的):GroupMessage:这里填写你的群号, napcat:FriendMessage:123456, telegram:FriendMessage:123456",
    "default": ["QQ号1:GroupMessage:603306240, QQ号2:GroupMessage:518516787"]
  },
  "push_time": {
    "description": "推送时间(以服务器时区为准)",
    "type": "string",
    "hint": "填写推送的时间，如: 08:00, 12:30, 18:00",
    "default": "08:00"
  },
  "show_text_news": {
    "description": "是否显示文字早报",
    "type": "bool",
    "hint": "是否显示文字早报，默认隐藏",
    "default": false
  },
  "use_local_image_draw": {
    "description": "是否使用本地图片绘制",
    "type": "bool",
    "hint": "是否使用本地图片绘制，为否则使用api获取图片",
    "default": true
  }
}
```

### 🛠️ 参数说明

下面是一份参数对照表:

| 参数名称             | 类型   | 默认值                                               | 描述                                          |
| -------------------- | ------ | ---------------------------------------------------- | --------------------------------------------- |
| target_groups        | list   | ["这里填你的平台名称:GroupMessage:这里填写你的群号"] | 需要推送 60s 早报的群组唯一标识符列表         |
| push_time            | string | "08:00"                                              | 推送时间(以服务器时区为准)                    |
| show_text_news       | bool   | false                                                | 是否显示文字早报，默认隐藏                    |
| use_local_image_draw | bool   | true                                                 | 是否使用本地图片绘制，为否则使用 api 获取图片 |

群聊唯一标识符分为: 前缀:中缀:后缀

# AstrBot 4.0 及以后群聊前缀直接填你自己起的名字, 例如我连接了 napcat 平台, 起名字叫"困困猫", 那么前缀就是"困困猫"!

AstrBot 4.0 及以前:

**下面是所有可选的群组唯一标识符前缀:**

| 平台                            | 群组唯一标识符前缀  |
| ------------------------------- | ------------------- |
| qq, napcat, Lagrange 之类的     | aiocqhttp           |
| qq 官方 bot                     | qq_official         |
| telegram                        | telegram            |
| 钉钉                            | dingtalk            |
| gewechat 微信(虽然已经停止维护) | gewechat            |
| lark                            | lark                |
| qq webhook 方法                 | qq_official_webhook |
| astrbot 网页聊天界面            | webchat             |

**下面是所有可选的群组唯一标识符中缀:**

| 群组唯一标识符中缀 | 描述     |
| ------------------ | -------- |
| GroupMessage       | 群组消息 |
| FriendMessage      | 私聊消息 |
| OtherMessage       | 其他消息 |

**群组唯一标识符后缀为群号, qq 号等**

下面提供部分示例:

1. napcat 平台向私聊用户 1350989414 推送消息, 我将平台命名为困困猫

   - `困困猫:FriendMessage:1350989414`

2. napcat 平台向群组 1350989414 推送消息

   - `aiocqhttp:GroupMessage:1350989414`

3. telegram 平台向私聊用户 1350989414 推送消息

   - `telegram:FriendMessage:1350989414`

4. telegram 平台向群组 1350989414 推送消息
   - `telegram:GroupMessage:1350989414`

## 📝 使用命令

### 查看插件状态

```
/get_status
```

显示当前配置的目标群组、推送时间、是否显示文字早报、使用本地图片绘制状态，以及距离下次推送的剩余时间。

### 获取当前群组 ID 配置

```
/get_config
```

显示当前消息来源的群组唯一标识符格式，帮助您正确配置目标群组。

### 测试发送功能

```
/test_send
```

向配置的所有目标群组发送测试消息，用于验证群组 ID 配置是否正确以及推送功能是否正常。

### 手动获取早报

```
/get_news [模式]
```

支持的模式:

- `image` - 仅推送图片早报
- `text` - 仅推送文字早报
- `all` - 同时推送图片和文字早报（默认）

此命令会将早报发送至请求获取早报的用户会话。

## 💡 使用提示

1. 为获得最佳体验，建议将推送时间设置在早晨（如 08:00），帮助群成员快速了解每日早报
2. 如果群内成员更喜欢文字阅读，可以将 `show_text_news` 设为 true
3. 使用 `/get_status` 命令可随时查看插件运行状态和下次推送时间
4. 使用 `/get_config` 命令可获取当前群组的正确 ID 格式，方便配置
5. 使用 `/test_send` 命令可测试群组配置是否正确
6. 如用户想自行获取早报，可使用 `/get_news` 命令手动获取

## 👥 贡献指南

欢迎通过以下方式参与项目：

- 🐛 提交 Issue 报告问题
- 💡 提出新功能建议
- 🔧 提交 Pull Request 改进代码

## 🌟 鸣谢

- 感谢以下每日 60 秒早报 API 提供的数据支持：

## 💖 支持

- [插件开发文档](https://docs.astrbot.app/dev/star/plugin-new.html)

---

> 信息知天下，六十秒读懂世界 📰
