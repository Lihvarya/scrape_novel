import requests
from bs4 import BeautifulSoup
import os
import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed  # 导入 as_completed

# 使用全局 Session，以便在多个请求之间重用TCP连接和cookies
global_session = requests.Session()


def get_page_info(url):
    """
    获取单个页面的信息：小说标题、作者、章节标题、正文内容，以及本页的下一页和下一章链接。
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    novel_title = "未知小说"
    author = "未知作者"
    chapter_title = "未知章节标题"
    chapter_content = ""
    next_page_link = None
    next_chapter_link = None

    try:
        response = global_session.get(url, headers=headers, timeout=15)  # 增加超时时间
        response.raise_for_status()
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')

        # 提取小说名称和作者
        novel_title_tag = soup.find('p', id='bookname')
        novel_title = novel_title_tag.text.strip() if novel_title_tag else novel_title

        author_tag = soup.find('p', id='author')
        author = author_tag.text.strip() if author_tag else author

        # 提取章节标题
        chapter_title_tag = soup.find('h1', class_='headline')
        if chapter_title_tag:
            chapter_title = chapter_title_tag.text.strip()

        # 提取正文内容
        content_div = soup.find('div', class_='content')
        if content_div:
            for p_tag in content_div.find_all('p'):
                text = p_tag.get_text(separator='\n', strip=True)
                if text:
                    chapter_content += text + '\n'

        # 清理不必要的文本
        # 使用正则表达式匹配并移除包含 "m.shuhaige.net" 或 "书海阁小说网" 的行
        chapter_content_lines = chapter_content.split('\n')
        cleaned_lines = [
            line for line in chapter_content_lines
            if "m.shuhaige.net" not in line and "书海阁小说网" not in line and "收藏" not in line
        ]
        chapter_content = "\n".join(cleaned_lines).strip()

        # 寻找导航链接
        pager_div = soup.find('div', class_='pager')
        if pager_div:
            # 寻找“下一页”链接
            # 根据提供的HTML，"上一页"和"下一章"是位于同一行，但是他们的href是不同的
            # "上一页" 和 "下一章" 的文本是固定的，用于章节间跳转
            # 而同一章节内的分页，通常是在URL后面加 _2.html, _3.html

            # 检查是否有显式“下一页”的链接文本 (在书海阁，这个链接通常表示同章节的下一页)
            next_page_a_tag = pager_div.find('a', string=lambda text: text and '下一页' in text)
            if next_page_a_tag and 'href' in next_page_a_tag.attrs:
                # 检查href是否指向当前章节的下一页
                href_path = next_page_a_tag['href']
                # 从当前URL中提取章节ID
                current_chapter_id_match = re.search(r'(\d+)(_\d+)?\.html', url)
                current_chapter_id = current_chapter_id_match.group(1) if current_chapter_id_match else None

                # 从下一页链接中提取章节ID和页码
                next_page_id_match = re.search(r'(\d+)(_(\d+))?\.html', href_path)
                next_page_chapter_id = next_page_id_match.group(1) if next_page_id_match else None
                next_page_current_page_num = int(
                    next_page_id_match.group(3)) if next_page_id_match and next_page_id_match.group(3) else 1

                # 如果下一页的章节ID与当前章节ID相同，并且页码大于当前页码（假设当前页码从URL解析）
                if current_chapter_id and next_page_chapter_id == current_chapter_id:
                    # 我们可以通过分析URL来判断当前页码，从而判断是否是下一页
                    current_page_match = re.search(r'(\d+)_(\d+)\.html$', url)
                    current_page_num_from_url = int(current_page_match.group(2)) if current_page_match else 1

                    if next_page_current_page_num == current_page_num_from_url + 1:
                        next_page_link = requests.compat.urljoin(url, href_path)
                    # 否则，它可能是 "上一页" 链接，或者其他不符合逻辑的链接，我们忽略

            # 寻找“下一章”链接
            next_chapter_a_tag = pager_div.find('a', string=lambda text: text and '下一章' in text)
            if next_chapter_a_tag and 'href' in next_chapter_a_tag.attrs:
                next_chapter_link = requests.compat.urljoin(url, next_chapter_a_tag['href'])

    except requests.exceptions.RequestException as e:
        print(f"请求页面URL失败: {url} - {e}")
    except Exception as e:
        print(f"解析页面内容失败: {url} - {e}")

    return {
        'novel_title': novel_title,
        'author': author,
        'chapter_title': chapter_title,
        'content': chapter_content,
        'next_page_link': next_page_link,
        'next_chapter_link': next_chapter_link,
        'original_url': url  # 保留原始URL以便排序
    }


def collect_all_urls_and_info(start_url):
    """
    通过广度优先搜索 (BFS) 收集所有章节和页面的URL，并预获取基本信息。
    """
    urls_to_visit = [start_url]
    visited_urls = set()
    all_page_info = {}  # 存储每个URL的初步信息

    novel_title = "未知小说"
    author = "未知作者"

    index = 0
    while index < len(urls_to_visit):
        current_url = urls_to_visit[index]
        index += 1

        if current_url in visited_urls:
            continue

        visited_urls.add(current_url)
        print(f"发现新页面: {current_url}")

        # 爬取当前页信息
        page_data = get_page_info(current_url)
        all_page_info[current_url] = page_data

        if novel_title == "未知小说" and page_data['novel_title'] != "未知小说":
            novel_title = page_data['novel_title']
        if author == "未知作者" and page_data['author'] != "未知作者":
            author = page_data['author']

        # 将下一页和下一章链接加入队列
        if page_data['next_page_link'] and page_data['next_page_link'] not in visited_urls:
            urls_to_visit.append(page_data['next_page_link'])

        # 只有在当前页没有下一页链接时，才考虑下一章链接
        # 这样确保了先爬完本章所有分页，再跳到下一章
        if not page_data['next_page_link'] and page_data['next_chapter_link'] and page_data[
            'next_chapter_link'] not in visited_urls:
            urls_to_visit.append(page_data['next_chapter_link'])

        time.sleep(0.05)  # 收集URL时也加一点小延迟

    return novel_title, author, all_page_info


def scrape_novel_concurrently(start_url, output_filename="小说.txt", max_workers=8):
    """
    首先收集所有章节和页面的URL，然后并发下载内容，最后按序写入。
    """
    # 1. 收集所有URL和初步信息
    print("阶段1: 收集所有章节和页面的URL及初步信息...")
    novel_title, author, all_page_info = collect_all_urls_and_info(start_url)

    if not all_page_info:
        print("未能收集到任何页面信息，程序终止。")
        return

    print(f"\n小说名称: {novel_title}")
    print(f"作者: {author}")
    print(f"共发现 {len(all_page_info)} 个页面。")
    print("阶段2: 排序章节和页面...")

    # 2. 排序所有页面 URL，确保章节和页面的顺序正确
    # 从 all_page_info 中提取 URL 及其对应的章节ID和页码
    sorted_urls_with_keys = []  # List of (chapter_id, page_num, url)
    for url, data in all_page_info.items():
        match = re.search(r'(\d+)(_(\d+))?\.html', url)
        if match:
            chapter_id = int(match.group(1))
            page_num = int(match.group(3)) if match.group(3) else 1
            sorted_urls_with_keys.append((chapter_id, page_num, url))
        else:
            # 如果URL模式不符合，无法排序，但也记录下来
            print(f"警告: 无法解析URL模式进行排序: {url}")
            sorted_urls_with_keys.append((0, 0, url))  # 放到前面或后面，可能乱序

    # 按章节ID和页码进行排序
    sorted_urls_with_keys.sort()

    print("阶段3: 并发下载内容并整理...")

    # 存储最终按顺序整理好的章节内容
    final_novel_content = []  # List of (chapter_title, full_chapter_content)
    current_chapter_content_buffer = []  # 缓冲区，存储当前章节所有页面的内容
    last_chapter_title = ""  # 用于跟踪当前正在处理的章节标题

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有需要下载的URL到线程池
        futures_map = {executor.submit(get_page_info, url_key[2]): url_key[2] for url_key in sorted_urls_with_keys}

        # 按照提交的顺序来获取结果（或者说，按照章节和页面的逻辑顺序处理结果）
        # 这里需要更精细的控制，因为 as_completed 是按完成顺序，而不是提交顺序
        # 所以，我们还是根据 sorted_urls_with_keys 的顺序来从 all_page_info 中获取内容
        # 但可以在获取内容时再判断一次是否已下载，如果未下载再提交

        # 更好的方法是：先收集所有URL，然后根据排序后的URL列表，逐个处理。
        # 在处理时，如果当前URL的内容还未下载，就提交给线程池。
        # 这样做可能会导致队列阻塞，所以我们换个思路：一次性把所有URL都提交给线程池。
        # 然后等待所有任务完成。最后再按顺序组装内容。

        # 重新提交所有URL，并等待全部完成，然后按序读取
        results_map = {}  # {url: page_data_result}
        for future in as_completed(futures_map):
            url = futures_map[future]
            try:
                page_data = future.result()
                results_map[url] = page_data
                print(f"  > 下载完成: {url}")
            except Exception as e:
                print(f"  × 下载URL {url} 失败: {e}")
            # time.sleep(0.05) # 每次完成一个任务后也稍微暂停一下

    print("\n阶段4: 整合内容并写入文件...")

    # 根据排序后的URL列表，整合章节内容
    chapter_count = 0
    with open(output_filename, 'w', encoding='utf-8') as f:
        f.write(f"小说名称: {novel_title}\n")
        f.write(f"作者: {author}\n\n")

        current_chapter_full_content = []
        last_chapter_title_written = ""

        for chapter_id, page_num, url in sorted_urls_with_keys:
            page_data = results_map.get(url)  # 从下载结果中获取数据
            if not page_data or not page_data['content']:
                print(f"警告: 页面 {url} 内容缺失，跳过。")
                continue

            current_page_chapter_title = page_data['chapter_title']

            # 如果是新章节的开始（或者第一章的第一个页面）
            if current_page_chapter_title != last_chapter_title_written and last_chapter_title_written != "":
                # 将上一章的内容写入文件
                if current_chapter_full_content:
                    f.write(f"\n\n--- {last_chapter_title_written} ---\n\n")
                    f.write("".join(current_chapter_full_content))
                    chapter_count += 1
                    print(f"  √ 写入章节: {last_chapter_title_written}")
                current_chapter_full_content = []  # 清空缓冲区，准备新章节

            # 添加当前页的内容到缓冲区
            current_chapter_full_content.append(page_data['content'])
            last_chapter_title_written = current_page_chapter_title  # 更新当前章节标题

        # 写入最后一章的内容
        if current_chapter_full_content:
            f.write(f"\n\n--- {last_chapter_title_written} ---\n\n")
            f.write("".join(current_chapter_full_content))
            chapter_count += 1
            print(f"  √ 写入最后一章: {last_chapter_title_written}")

    print(f"\n小说 '{novel_title}' 爬取完成！共写入 {chapter_count} 章，所有内容已保存到 '{output_filename}'")


if __name__ == "__main__":
    novel_start_chapter_url = "https://m.shuhaige.net/386996/132381581.html"
    output_file = "全员恶仙！！！.txt"

    # 推荐的并发数一般在 4-16 之间，取决于你的网络带宽和目标网站的承受能力
    scrape_novel_concurrently(novel_start_chapter_url, output_file, max_workers=8)
