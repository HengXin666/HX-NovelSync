# HX-NovelSync
> [!TIP]
> [个人自用] 小说同步: 基于番茄小说API定时爬取并推送. 基于Github工作流

## 使用方式

1. 编辑 `novels.json`，在 `novels` 数组中添加要追踪的小说：
```json
{
  "novels": [
    {
      "name": "小说完整名称",
      "author": "作者名",
      "book_id": "番茄小说ID（数字）"
    }
  ]
}
```

> book_id 可以从番茄小说网页版链接中获取，例如 `https://fanqienovel.com/page/7404826300126333977` 中的 `7404826300126333977`

2. 工作流每天北京时间早上8点自动执行，也可以手动触发
3. 下载完成后自动发布到 Release，文件命名格式为 `书名-作者.txt`
4. Release 页面显示某书的总章节数, 以及最新章节名称

## 当前追踪列表

1. 《全民巨鱼求生：我能听到巨鱼心声》[作者:失控云]

## 数据源

基于番茄小说API（参考 [Tomato-Novel-Downloader](https://github.com/zhongbai2333/Tomato-Novel-Downloader) 项目）
