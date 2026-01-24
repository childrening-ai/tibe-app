import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import re

# --- 1. 設定區 (已更新為 2026 日期) ---
BASE_URL = "https://www.tibe.org.tw/tw/calendar"

# 請確認這些 ID (69, 70...) 對應到的網頁真的是 2026 的活動
# 如果官網還沒更新 2026，抓到的可能會是舊資料
DATE_MAP = {
    "2026-02-03 (二)": "69",
    "2026-02-04 (三)": "70",
    "2026-02-05 (四)": "71",
    "2026-02-06 (五)": "72",
    "2026-02-07 (六)": "73",
    "2026-02-08 (日)": "74",
}

# --- 2. 強力清洗函式 (解決資料錯置關鍵) ---
def clean_text(text):
    if not text:
        return ""
    # 1. 將 HTML 的 <br> 換成空白
    # 2. 去除前後空白
    text = text.strip()
    # 3. 將內部的換行符號 (\n, \r) 替換成空白，避免 CSV 斷行
    text = re.sub(r'[\r\n]+', ' ', text)
    # 4. 將逗號 (,) 替換成全形逗號 (，)，避免 CSV 欄位位移
    text = text.replace(',', '，')
    # 5. 移除多餘的連續空白
    text = re.sub(r'\s+', ' ', text)
    return text

def scrape_single_page(url):
    """抓取單一頁面"""
    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            return [], False
            
        soup = BeautifulSoup(response.text, 'html.parser')
        items = soup.find_all(class_="calendar-item")
        
        if not items:
            return [], False

        page_events = []
        for item in items:
            title_el = item.find(class_="header-text")
            if not title_el: continue
            
            # 初始化欄位
            event_data = {
                "日期": "", # 稍後填入
                "時間": "", 
                "活動名稱": clean_text(title_el.text),
                "地點": "", 
                "主講人": "", 
                "主持人": "", 
                "類型": "講座",
                "備註": "",
                "詳細內容": ""
            }
            
            # 解析 Info 區塊 (時間/地點/主講)
            for label in item.find_all(class_="info-name"):
                val = label.find_next_sibling(class_="info-text")
                if not val: val = label.find_previous_sibling(class_="info-text")
                
                if val:
                    # 🔥 這裡每一項都經過 clean_text 清洗
                    txt = clean_text(val.text)
                    if "時間" in label.text: event_data["時間"] = txt
                    elif "地點" in label.text: event_data["地點"] = txt
                    elif "主講" in label.text: event_data["主講人"] = txt
                    elif "主持" in label.text: event_data["主持人"] = txt
            
            # 解析詳細內容
            desc = item.find(class_="web-editor")
            if desc:
                # 🔥 詳細內容最容易出事，一定要清洗換行
                full_text = clean_text(desc.text)
                event_data["詳細內容"] = full_text
                # 備註只取前 30 字
                event_data["備註"] = full_text[:30] + "..." if len(full_text) > 30 else full_text
            
            # 簡單類型判斷
            name_chk = event_data["活動名稱"]
            loc_chk = event_data["地點"]
            if "簽書" in name_chk or "簽名" in name_chk: event_data["類型"] = "簽書會"
            elif "直播" in loc_chk: event_data["類型"] = "直播活動"
            elif "沙龍" in loc_chk: event_data["類型"] = "沙龍講座"
            elif "DIY" in name_chk or "手作" in name_chk: event_data["類型"] = "手作活動"

            page_events.append(event_data)
            
        return page_events, True
        
    except Exception as e:
        print(f"⚠️ 爬蟲錯誤: {e}")
        return [], False

def main():
    print("🚀 開始抓取資料 (2026 日期修正版)...")
    all_data = []
    
    for date_str, date_id in DATE_MAP.items():
        # 只取日期部分，例如 "2026-02-03" (去除星期幾，為了 CSV 乾淨)
        clean_date_only = date_str.split(" ")[0]
        
        print(f"\n📅 正在處理: {date_str} (ID: {date_id})")
        page = 1
        
        while True:
            url = f"{BASE_URL}/{date_id}?page={page}"
            # print(f"   - 抓取第 {page} 頁...") # 註解掉避免太吵
            
            events, has_data = scrape_single_page(url)
            
            if has_data and events:
                # 🔥 在這裡統一填入日期，絕對不會錯
                for e in events:
                    e['日期'] = clean_date_only
                
                all_data.extend(events)
                page += 1
                time.sleep(0.3)
            else:
                print(f"   ✅ 完成，共 {page-1} 頁。")
                break
            
            if page > 30: break # 安全煞車

    # --- 輸出結果 ---
    if all_data:
        df = pd.DataFrame(all_data)
        
        # 確保欄位順序
        cols = ["日期", "時間", "活動名稱", "地點", "主講人", "主持人", "類型", "備註", "詳細內容"]
        df = df[cols]
        
        # 輸出 CSV
        filename = "2026_tibe_events_fixed.csv"
        df.to_csv(filename, index=False, encoding="utf-8-sig")
        
        print("\n" + "="*30)
        print(f"🎉 抓取成功！")
        print(f"📁 檔案已儲存: {filename}")
        print(f"📊 總筆數: {len(df)}")
        print("💡 這次的 CSV 已經清除了換行符號，應該不會再跑版了！")
    else:
        print("❌ 沒抓到資料，請檢查網址或 ID 是否正確。")

if __name__ == "__main__":
    main()