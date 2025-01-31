# 1. 필요한 라이브러리 불러오기
from bs4 import BeautifulSoup
import requests
from transformers import pipeline
from datetime import datetime
from googletrans import Translator
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import os

os.environ["TOKENIZERS_PARALLELISM"] = "false"

# 2. 뉴스 스크래핑 함수
def scrape_news():
    # Selenium WebDriver 설정
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

    search_terms = [
        "US GDP growth",
        "US economic indicators",
        "US manufacturing data",
        "US retail sales",
        "US inflation rate",
        "US employment report",
        "Federal Reserve decision",
        "US Treasury yields",
        "US stock market outlook",
        "Wall Street analysis",
        "US corporate earnings",
        "US tech sector news",
        "US business investment",
        "US trade balance",
        "US dollar forex",
        "US economic policy"
    ]

    news_results = []
    for term in search_terms:
        url = f"https://news.google.com/rss/search?q={term}&hl=en-US&gl=US&ceid=US:en"
        try:
            driver.get(url)
            soup = BeautifulSoup(driver.page_source, "lxml-xml")

            for item in soup.find_all("item")[:7]:
                pub_date = item.pubDate.text if item.pubDate else ""
                if pub_date:
                    pub_date = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %Z")
                    if (datetime.now() - pub_date).days >= 2:
                        continue

                link = item.link.text if item.link else ""
                if any(x in link.lower() for x in ['.pdf', 'youtube.com', 'youtu.be']):
                    continue

                title = item.title.text if item.title else ""
                if any(x in title.lower() for x in ['video:', 'podcast:', 'watch:']):
                    continue

                news_results.append({
                    "title": title,
                    "link": link,
                    "description": item.description.text if item.description else "",
                    "pub_date": pub_date.strftime("%Y-%m-%d %H:%M:%S")
                })

        except Exception as e:
            print(f"Error fetching news for term '{term}': {e}")
            continue

    driver.quit()

    unique_news = list({news['link']: news for news in news_results}.values())
    return sorted(unique_news, key=lambda x: datetime.strptime(x['pub_date'], "%Y-%m-%d %H:%M:%S"), reverse=True)

# 3. 기사 내용 가져오기 및 요약 함수
def get_article_content(url):
    try:
        response = requests.get(url)
        soup = BeautifulSoup(response.content, "html.parser")

        article_text = ""
        article_tags = [("article",),
                        ("div", {"class": "article-body"}),
                        ("div", {"class": "article-content"}),
                        ("div", {"class": "story-body"}),
                        ("div", {"class": "content"}),
                        ("div", {"class": "main-content"})]

        for tag, attrs in article_tags:
            elements = soup.find_all(tag, attrs=attrs if attrs else None)
            if elements:
                article_text = ' '.join([el.text.strip() for el in elements])
                if article_text:
                    break

        if not article_text:
            article_text = ' '.join([p.text.strip() for p in soup.find_all("p") if len(p.text) > 100])

        if not article_text:
            return "기사 내용을 가져올 수 없습니다."

        summarizer = pipeline("summarization", model="facebook/bart-large-cnn")
        chunks = [article_text[i:i+500] for i in range(0, len(article_text), 500)]
        summaries = []

        for chunk in chunks[:3]:
            if len(chunk) > 100:
                summary = summarizer(chunk, max_length=150, min_length=50, do_sample=False)
                summaries.append(summary[0]['summary_text'])

        final_summary = ' '.join(summaries)
        return translate_to_korean(final_summary)

    except Exception as e:
        print(f"Error processing article {url}: {e}")
        return "기사 내용을 가져올 수 없습니다."

# 4. 기사 제목 한글 번역 함수
def translate_to_korean(text):
    translator = Translator()
    return translator.translate(text, dest='ko').text

# 5. 시트 생성 함수
def create_daily_sheet(client, spreadsheet_name):
    today = datetime.now().strftime('%Y-%m-%d')
    spreadsheet = client.open(spreadsheet_name)

    try:
        worksheet = spreadsheet.worksheet(today)
    except:
        worksheet = spreadsheet.add_worksheet(title=today, rows=101, cols=4)

    return worksheet

# 6. 스프레드시트 업데이트 함수
def update_spreadsheet(news_data):
    scope = ['https://spreadsheets.google.com/feeds',
             'https://www.googleapis.com/auth/drive']
    credentials = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
    client = gspread.authorize(credentials)
    
    sheet = create_daily_sheet(client, '미국증시_일일리포트')
    
    headers = ['날짜', '제목', '링크', '요약', '한국어제목']
    sheet.update(values=[headers], range_name='A1:E1')

    current_date = datetime.now().strftime('%Y-%m-%d')

    rows = []
    for news in news_data[:25]:
        detailed_summary = get_article_content(news['link'])
        translated_title = translate_to_korean(news['title'])
        rows.append([
            current_date,
            news['title'],
            news['link'],
            detailed_summary,
            translated_title
        ])

    sheet.update(values=rows, range_name='A2:E26')
    print("스프레드시트 업데이트 완료!")

# 7. 메인 실행 코드
if __name__ == "__main__":
    print("뉴스 수집 시작...")
    news_data = scrape_news()
    print(f"{len(news_data)}개의 뉴스를 찾았습니다.")

    print("\n스프레드시트 업데이트 중...")
    update_spreadsheet(news_data)
