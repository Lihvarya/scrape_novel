import requests
from bs4 import BeautifulSoup
import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple, Optional, Set
from dataclasses import dataclass
import logging
from threading import Lock
from queue import Queue


# ==================== 配置区域 ====================
class Config:
    """爬虫配置类"""
    REQUEST_TIMEOUT = 15
    MAX_RETRIES = 3
    RETRY_DELAY = 2

    MAX_WORKERS = 8  # 下载内容时的最大并发线程数
    COLLECT_WORKERS = 4  # 收集URL时的并发线程数

    COLLECT_DELAY = 0.05
    DOWNLOAD_DELAY = 0.05

    USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    FILTER_KEYWORDS = ['m.shuhaige.net', '书海阁小说网', '收藏', '更新速度全网最快']


# ==================== 数据结构 ====================
@dataclass
class PageInfo:
    """页面信息数据类"""
    url: str
    novel_title: str = "未知小说"
    author: str = "未知作者"
    chapter_title: str = "未知章节"
    content: str = ""
    next_page_link: Optional[str] = None
    next_chapter_link: Optional[str] = None
    chapter_id: int = 0
    page_num: int = 1


# ==================== 日志配置 ====================
def setup_logging():
    """配置日志"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )
    return logging.getLogger(__name__)


logger = setup_logging()


# ==================== 核心爬虫类 ====================
class NovelSpider:
    """小说爬虫类"""

    def __init__(self, start_url: str, output_file: str = "小说.txt"):
        self.start_url = start_url
        self.output_file = output_file
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': Config.USER_AGENT})

    def _parse_url_info(self, url: str) -> Tuple[int, int]:
        """从URL中解析章节ID和页码"""
        match = re.search(r'(\d+)(_(\d+))?\.html', url)
        if match:
            chapter_id = int(match.group(1))
            page_num = int(match.group(3)) if match.group(3) else 1
            return chapter_id, page_num
        return 0, 1

    def _clean_content(self, content: str) -> str:
        """清理内容中的广告和无关文本"""
        lines = content.split('\n')
        cleaned_lines = [
            line for line in lines
            if not any(keyword in line for keyword in Config.FILTER_KEYWORDS)
        ]
        return '\n'.join(cleaned_lines).strip()

    def _fetch_page(self, url: str, retry_count: int = 0) -> Optional[requests.Response]:
        """获取页面内容，支持重试"""
        try:
            response = self.session.get(url, timeout=Config.REQUEST_TIMEOUT)
            response.raise_for_status()
            response.encoding = 'utf-8'
            return response
        except requests.exceptions.RequestException as e:
            if retry_count < Config.MAX_RETRIES:
                logger.warning(f"请求失败，{Config.RETRY_DELAY}秒后重试 ({retry_count + 1}/{Config.MAX_RETRIES}): {url}")
                time.sleep(Config.RETRY_DELAY)
                return self._fetch_page(url, retry_count + 1)
            else:
                logger.error(f"请求失败，已达最大重试次数: {url} - {e}")
                return None

    def parse_page(self, url: str) -> PageInfo:
        """解析单个页面，提取所有信息"""
        response = self._fetch_page(url)
        if not response:
            return PageInfo(url=url)

        try:
            soup = BeautifulSoup(response.text, 'html.parser')

            # 提取基本信息
            novel_title_tag = soup.find('p', id='bookname')
            novel_title = novel_title_tag.text.strip() if novel_title_tag else "未知小说"

            author_tag = soup.find('p', id='author')
            author = author_tag.text.strip() if author_tag else "未知作者"

            chapter_title_tag = soup.find('h1', class_='headline')
            chapter_title = chapter_title_tag.text.strip() if chapter_title_tag else "未知章节"

            # 提取正文
            content = ""
            content_div = soup.find('div', class_='content')
            if content_div:
                paragraphs = content_div.find_all('p')
                content = '\n'.join(
                    p.get_text(separator='\n', strip=True) for p in paragraphs if p.get_text(strip=True))
                content = self._clean_content(content)

            # 解析URL信息
            chapter_id, page_num = self._parse_url_info(url)

            # 查找导航链接
            next_page_link = None
            next_chapter_link = None

            pager_div = soup.find('div', class_='pager')
            if pager_div:
                for a_tag in pager_div.find_all('a'):
                    link_text = a_tag.text.strip()
                    href = a_tag.get('href', '')

                    if not href:
                        continue

                    full_url = requests.compat.urljoin(url, href)
                    link_chapter_id, link_page_num = self._parse_url_info(full_url)

                    # 判断是否为下一页（同章节，页码+1）
                    if link_chapter_id == chapter_id and link_page_num == page_num + 1:
                        next_page_link = full_url
                    # 判断是否为下一章（章节ID不同）
                    elif '下一章' in link_text and link_chapter_id != chapter_id:
                        next_chapter_link = full_url

            return PageInfo(
                url=url,
                novel_title=novel_title,
                author=author,
                chapter_title=chapter_title,
                content=content,
                next_page_link=next_page_link,
                next_chapter_link=next_chapter_link,
                chapter_id=chapter_id,
                page_num=page_num
            )

        except Exception as e:
            logger.error(f"解析页面失败: {url} - {e}")
            return PageInfo(url=url)

    def collect_all_urls_concurrent(self) -> Tuple[str, str, List[str]]:
        """
        并发收集所有章节和页面的URL（修复版）
        使用队列和线程池的方式
        """
        logger.info("=" * 60)
        logger.info("阶段 1/3: 并发收集所有章节和页面URL")
        logger.info("=" * 60)

        # 初始化
        url_queue = Queue()
        url_queue.put(self.start_url)

        visited_urls = set()
        url_list = []
        lock = Lock()

        novel_info = {'title': "未知小说", 'author': "未知作者"}

        def process_url(url: str):
            """处理单个URL的工作函数"""
            # 检查是否已访问
            with lock:
                if url in visited_urls:
                    return
                visited_urls.add(url)
                url_list.append(url)
                current_count = len(url_list)

            logger.info(f"发现页面 [{current_count}]: {url}")

            # 解析页面
            page_info = self.parse_page(url)

            # 更新小说信息
            with lock:
                if novel_info['title'] == "未知小说" and page_info.novel_title != "未知小说":
                    novel_info['title'] = page_info.novel_title
                if novel_info['author'] == "未知作者" and page_info.author != "未知作者":
                    novel_info['author'] = page_info.author

            # 将新发现的URL加入队列
            if page_info.next_page_link:
                with lock:
                    if page_info.next_page_link not in visited_urls:
                        url_queue.put(page_info.next_page_link)
            elif page_info.next_chapter_link:
                with lock:
                    if page_info.next_chapter_link not in visited_urls:
                        url_queue.put(page_info.next_chapter_link)

            time.sleep(Config.COLLECT_DELAY)

        # 使用线程池处理队列
        with ThreadPoolExecutor(max_workers=Config.COLLECT_WORKERS) as executor:
            futures = set()

            while True:
                # 从队列中获取URL并提交任务
                while not url_queue.empty() and len(futures) < Config.COLLECT_WORKERS:
                    url = url_queue.get()
                    future = executor.submit(process_url, url)
                    futures.add(future)

                # 如果没有正在执行的任务且队列为空，说明收集完成
                if not futures and url_queue.empty():
                    break

                # 等待至少一个任务完成
                if futures:
                    done, futures = as_completed(futures).__next__(), futures - {as_completed(futures).__next__()}
                    # 更简洁的写法
                    completed = set()
                    for future in list(futures):
                        if future.done():
                            completed.add(future)
                            try:
                                future.result()
                            except Exception as e:
                                logger.error(f"处理URL时出错: {e}")
                    futures -= completed

                # 短暂休眠，避免CPU空转
                time.sleep(0.01)

        logger.info(f"\n收集完成！")
        logger.info(f"小说名称: {novel_info['title']}")
        logger.info(f"作者: {novel_info['author']}")
        logger.info(f"总页面数: {len(url_list)}")

        return novel_info['title'], novel_info['author'], url_list

    def download_pages_concurrently(self, url_list: List[str]) -> Dict[str, PageInfo]:
        """并发下载所有页面内容"""
        logger.info("\n" + "=" * 60)
        logger.info("阶段 2/3: 并发下载页面内容")
        logger.info("=" * 60)

        results = {}
        completed_count = 0
        total_count = len(url_list)

        with ThreadPoolExecutor(max_workers=Config.MAX_WORKERS) as executor:
            future_to_url = {executor.submit(self.parse_page, url): url for url in url_list}

            for future in as_completed(future_to_url):
                url = future_to_url[future]
                completed_count += 1

                try:
                    page_info = future.result()
                    results[url] = page_info

                    progress = (completed_count / total_count) * 100
                    logger.info(
                        f"下载进度: [{completed_count}/{total_count}] {progress:.1f}% - {page_info.chapter_title}")

                except Exception as e:
                    logger.error(f"下载失败: {url} - {e}")
                    results[url] = PageInfo(url=url)

                time.sleep(Config.DOWNLOAD_DELAY)

        logger.info(f"\n下载完成！成功: {len(results)}/{total_count}")
        return results

    def write_novel(self, novel_title: str, author: str, url_list: List[str], page_data: Dict[str, PageInfo]):
        """将小说内容写入文件"""
        logger.info("\n" + "=" * 60)
        logger.info("阶段 3/3: 整理并写入文件")
        logger.info("=" * 60)

        sorted_urls = sorted(url_list, key=lambda url: self._parse_url_info(url))

        chapter_count = 0
        current_chapter_content = []
        last_chapter_title = ""

        with open(self.output_file, 'w', encoding='utf-8') as f:
            f.write(f"小说名称: {novel_title}\n")
            f.write(f"作者: {author}\n")
            f.write(f"来源: 书海阁小说网\n")
            f.write(f"爬取时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 60 + "\n\n")

            for url in sorted_urls:
                page_info = page_data.get(url)
                if not page_info or not page_info.content:
                    logger.warning(f"跳过空内容页面: {url}")
                    continue

                if page_info.chapter_title != last_chapter_title:
                    if current_chapter_content:
                        f.write(f"\n\n{'=' * 60}\n")
                        f.write(f"{last_chapter_title}\n")
                        f.write(f"{'=' * 60}\n\n")
                        f.write('\n\n'.join(current_chapter_content))
                        chapter_count += 1
                        logger.info(f"写入章节 [{chapter_count}]: {last_chapter_title}")

                    current_chapter_content = []
                    last_chapter_title = page_info.chapter_title

                current_chapter_content.append(page_info.content)

            if current_chapter_content:
                f.write(f"\n\n{'=' * 60}\n")
                f.write(f"{last_chapter_title}\n")
                f.write(f"{'=' * 60}\n\n")
                f.write('\n\n'.join(current_chapter_content))
                chapter_count += 1
                logger.info(f"写入章节 [{chapter_count}]: {last_chapter_title}")

        logger.info(f"\n{'=' * 60}")
        logger.info(f"爬取完成！")
        logger.info(f"小说: {novel_title}")
        logger.info(f"章节数: {chapter_count}")
        logger.info(f"保存位置: {self.output_file}")
        logger.info(f"{'=' * 60}")

    def run(self):
        """运行爬虫"""
        start_time = time.time()

        try:
            novel_title, author, url_list = self.collect_all_urls_concurrent()

            if not url_list:
                logger.error("未能收集到任何页面，程序终止")
                return

            page_data = self.download_pages_concurrently(url_list)
            self.write_novel(novel_title, author, url_list, page_data)

            elapsed_time = time.time() - start_time
            logger.info(f"\n总耗时: {elapsed_time:.2f} 秒")
            logger.info(f"平均速度: {len(url_list) / elapsed_time:.2f} 页/秒")

        except KeyboardInterrupt:
            logger.warning("\n用户中断，程序退出")
        except Exception as e:
            logger.error(f"\n程序异常: {e}", exc_info=True)
        finally:
            self.session.close()


# ==================== 主程序入口 ====================
def main():
    """主函数"""
    start_url = "https://m.shuhaige.net/386996/132381581.html"
    output_file = "全员恶仙！！！.txt"

    spider = NovelSpider(start_url, output_file)
    spider.run()


if __name__ == "__main__":
    main()
