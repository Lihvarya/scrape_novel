### 小说爬虫脚本 (scrape_novel.py)

这是一个用于从特定在线小说网站（例如：`m.shuhaige.net`）爬取小说内容并保存到本地文本文件的 Python 脚本。它能够处理章节内的多页内容，并以正确的顺序整理和输出小说。

## 功能

* **并发下载**：利用 `ThreadPoolExecutor` 实现多线程并发下载章节内容，提高爬取效率。
* **智能导航**：自动识别并处理同一章节内的分页链接 (`_2.html`, `_3.html` 等)，确保完整爬取整个章节；并在当前章节所有页爬取完毕后，自动跳转到下一章节。
* **内容清理**：自动移除小说正文中可能包含的广告、水印、版权声明等不相关文本（如 "m.shuhaige.net", "书海阁小说网", "收藏" 等）。
* **顺序输出**：在并发下载所有页面信息后，根据章节ID和页码对内容进行智能排序，确保小说内容以正确的章节和页码顺序写入文件。
* **会话管理**：使用 `requests.Session` 提高请求效率，复用 TCP 连接和 Cookies。
* **信息提取**：能够自动识别小说标题、作者和章节标题。
* **断点续传（部分）**：虽然没有明确的断点续传功能，但由于先收集所有URL再下载的机制，如果在下载过程中中断，已收集的URL信息不会丢失，但已下载的文件需要重新运行。

## 要求

* Python 3.x
* `requests` 库
* `BeautifulSoup4` 库

## 安装

1. 将 `scrape_novel.py` 文件下载到你的本地计算机。
2. 安装所需的 Python 库。推荐使用 `pip`：

   ```bash
   pip install requests beautifulsoup4
   ```

## 使用方法

1. 打开 `scrape_novel.py` 文件。
2. 修改 `if __name__ == "__main__":` 块中的配置变量，特别是 `novel_start_chapter_url` 和 `output_file`。
3. 运行脚本：

   ```bash
   python scrape_novel.py
   ```

脚本将开始收集所有章节和页面的URL，然后并发下载内容，最后将小说内容按顺序写入指定的输出文件。

## 配置

在 `if __name__ == "__main__":` 块中，你可以配置以下变量：

* `novel_start_chapter_url` (str): **必填**。你要爬取的小说的起始章节 URL。例如：`"https://m.shuhaige.net/386996/132381581.html"`。
* `output_file` (str): **可选**。保存小说内容的文本文件名。默认为 `"小说.txt"`。
* `max_workers` (int): **可选**。用于并发下载的线程数。根据你的网络带宽和目标网站的承受能力，可以适当调整。推荐值通常在 4-16 之间。默认为 `8`。

```python
if __name__ == "__main__":
    # 配置你要爬取的小说起始章节URL
    novel_start_chapter_url = "https://m.shuhaige.net/386996/132381581.html"

    # 配置输出文件名
    output_file = "全员恶仙！！！.txt"

    # 配置并发下载的线程数 (推荐 4-16)
    max_workers = 8

    scrape_novel_concurrently(novel_start_chapter_url, output_file, max_workers)
```

## 注意事项

* **网站特异性**：此脚本是为 `m.shuhaige.net` 这类网站的特定 HTML 结构和 URL 模式设计的。如果目标网站的 HTML 结构或 URL 规则发生变化，脚本可能需要进行修改才能正常工作。
* **伦理与合法性**：请在遵守目标网站的 `robots.txt` 协议、使用条款和当地法律法规的前提下使用本脚本。请勿对网站造成过大压力，避免频繁请求，以免被封禁 IP 或对网站正常运行造成影响。
* **反爬机制**：部分网站可能具备更复杂的反爬机制（如验证码、动态加载内容等），本脚本可能无法应对这些情况。
* **网络波动**：网络连接不稳定可能导致请求失败，脚本中已加入超时设置和错误捕获，但仍可能出现少量章节或页面无法爬取的情况。
