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

# 2. 브라우저 설정 함수
def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument('--headless')  # 브라우저 창 안보이게
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.binary_location = '/usr/bin/google-chrome'
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

# 3. 번역 함수
def translate_to_korean(text):
    translator = Translator()
    try:
        result = translator.translate(text, dest='ko')
        return result.text
    except:
        return text  # 번역 실패시 원문 반환

# 4. 뉴스 수집 함수
def scrape_news():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    # 카테고리별로 검색어 구성
    search_terms = {
        # 주요 경제 지표
        "US GDP growth",
        "US economic indicators",
        "US manufacturing data",
        "US retail sales",
        "US inflation rate",
        "US employment report",
        
        # 금융 시장
        "Federal Reserve decision",
        "US Treasury yields",
        "US stock market outlook",
        "Wall Street analysis",
        
        # 산업/기업
        "US corporate earnings",
        "US tech sector news",
        "US business investment",
        
        # 대외 관계
        "US trade balance",
        "US dollar forex",
        "US economic policy"
    }
    
    news_results = []
    for term in search_terms:
        url = f"https://news.google.com/rss/search?q={term}&hl=en-US&gl=US&ceid=US:en"
        try:
            response = requests.get(url, headers=headers)
            soup = BeautifulSoup(response.content, "lxml-xml")
            
            for item in soup.find_all("item")[:7]:  # 각 키워드당 7개만 수집
                # 게시일 확인 - 48시간 이내의 뉴스 수집
                pub_date = item.pubDate.text if item.pubDate else ""
                if pub_date:
                    pub_date = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %Z")
                    time_diff = datetime.now() - pub_date
                    if time_diff.days >= 2:  # 48시간 이상 지난 뉴스는 제외
                        continue
                        
                link = item.link.text if item.link else ""
                # PDF와 동영상 사이트만 제외
                if any(x in link.lower() for x in ['.pdf', 'youtube.com', 'youtu.be']):
                    continue
                
                # 제목에 'video', 'podcast' 포함된 경우 제외
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
    
    # 중복 제거 및 최신 순으로 정렬
    unique_news = list({news['link']: news for news in news_results}.values())
    sorted_news = sorted(unique_news, 
                        key=lambda x: datetime.strptime(x['pub_date'], "%Y-%m-%d %H:%M:%S"),
                        reverse=True)
    
    return sorted_news

# 5. 기사 내용 가져오기 및 요약 함수
def get_article_content(url):
    try:
        driver = setup_driver()
        driver.get(url)
        time.sleep(5)  # 페이지 로딩 대기 시간 증가
        
        # 다양한 방법으로 본문 내용 추출 시도
        article_text = ""
        
        # 1. article 태그 시도
        articles = driver.find_elements(By.TAG_NAME, "article")
        if articles:
            article_text = articles[0].text
        
        # 2. 특정 클래스로 시도
        if not article_text:
            possible_content_classes = ['article-body', 'article-content', 'story-body', 'content', 'main-content']
            for class_name in possible_content_classes:
                elements = driver.find_elements(By.CLASS_NAME, class_name)
                if elements:
                    article_text = elements[0].text
                    break
        
        # 3. p 태그들 시도
        if not article_text:
            paragraphs = driver.find_elements(By.TAG_NAME, "p")
            article_text = ' '.join([p.text for p in paragraphs if len(p.text.strip()) > 100])
        
        driver.quit()
        
        if not article_text:
            return "기사 내용을 가져올 수 없습니다."
            
        # 요약 생성
        summarizer = pipeline("summarization", model="facebook/bart-large-cnn")
        chunks = [article_text[i:i+500] for i in range(0, len(article_text), 500)]
        summaries = []
        
        for chunk in chunks[:3]:
            if len(chunk) > 100:
                summary = summarizer(chunk, max_length=250, min_length=150)
                summaries.append(summary[0]['summary_text'])
        
        final_summary = ' '.join(summaries)
        korean_summary = translate_to_korean(final_summary)
        return korean_summary
        
    except Exception as e:
        print(f"Error processing article {url}: {e}")
        if 'driver' in locals():
            driver.quit()
        return "기사 내용을 가져올 수 없습니다."

# 6. 시트 생성 함수
def create_daily_sheet(client, spreadsheet_name):
    today = datetime.now().strftime('%Y-%m-%d')
    spreadsheet = client.open(spreadsheet_name)
    
    try:
        worksheet = spreadsheet.worksheet(today)
    except:
        worksheet = spreadsheet.add_worksheet(title=today, rows=101, cols=4)
    
    return worksheet

# 7. 스프레드시트 업데이트 함수
def update_spreadsheet(news_data):
    scope = ['https://spreadsheets.google.com/feeds',
             'https://www.googleapis.com/auth/drive']
    credentials = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
    client = gspread.authorize(credentials)
    
    sheet = create_daily_sheet(client, '미국증시_일일리포트')
    
    headers = ['날짜', '제목', '링크', '요약']
    sheet.update(values=[headers], range_name='A1:D1')
    
    current_date = datetime.now().strftime('%Y-%m-%d')
    
    rows = []
    for news in news_data[:25]:
        detailed_summary = get_article_content(news['link'])
        rows.append([
            current_date,
            news['title'],
            news['link'],
            detailed_summary
        ])
    
    sheet.update(values=rows, range_name='A2:D26')
    print("스프레드시트 업데이트 완료!")

# 8. 메인 실행 코드
if __name__ == "__main__":
    print("뉴스 수집 시작...")
    news_data = scrape_news()
    print(f"{len(news_data)}개의 뉴스를 찾았습니다.")
    
    print("\n스프레드시트 업데이트 중...")
    update_spreadsheet(news_data)
