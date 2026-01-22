import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
from ics import Calendar, Event
import time
import random
import datetime
from streamlit_calendar import calendar

# 設定頁面 (設為寬版以便顯示雙欄)
st.set_page_config(page_title="書展排程神器", page_icon="📅", layout="wide")

# --- 側邊欄：使用說明 ---
with st.sidebar:
    st.header("📖 使用說明")
    st.info("第一次使用請先看這裡！")
    
    st.markdown("""
    ### 📚 爸媽逛書展神隊友
    **3 步驟訂製您的專屬行程**

    **1. 一鍵更新 🚀**
    點擊右側的「抓取書展全資料」，幫您把幾百場活動瞬間抓進來！

    **2. 勾選喜歡 ✅**
    在清單看到喜歡的繪本講座，直接打勾。日曆會幫您檢查有沒有撞期。

    **3. 帶了就走 🎒**
    選好後，您可以選擇最適合您的方式：
    * 📲 **同步手機**：下載 `.ics` 檔，自動加入手機行事曆（會跳出提醒喔！）。
    * 🖨️ **列印清單**：下載 Excel 表格，印出來勾選最方便。
    * 💬 **傳送分享**：複製下方的「文字懶人包」，直接傳到 Line 家人群組！
    """)
    
    st.divider()
    st.caption("Designed for 2025 TIBE")

# --- 主畫面標題 ---
st.title("📅 2025 台北國際書展 - 智慧排程助手")
st.markdown("先抓取資料，再勾選您感興趣的活動，右側會即時預覽您的行程表！")

# 基礎設定
BASE_URL = "https://www.tibe.org.tw/tw/calendar"
DATE_MAP = {
    "2025-02-03 (一)": "69",
    "2025-02-04 (二)": "70",
    "2025-02-05 (三)": "71",
    "2025-02-06 (四)": "72",
    "2025-02-07 (五)": "73",
    "2025-02-08 (六)": "74",
}

# --- 核心工具：時間清洗函式 ---
def parse_time_range(date_str, time_str):
    try:
        clean_date = date_str.split(" ")[0]
        if "-" not in time_str:
            return None, None 
            
        start_t, end_t = time_str.split("-")
        start_t = start_t.strip()
        end_t = end_t.strip()
        
        start_dt_str = f"{clean_date} {start_t}"
        end_dt_str = f"{clean_date} {end_t}"
        
        start_dt = datetime.datetime.strptime(start_dt_str, "%Y-%m-%d %H:%M")
        end_dt = datetime.datetime.strptime(end_dt_str, "%Y-%m-%d %H:%M")
        
        return start_dt, end_dt
    except Exception as e:
        return None, None

# --- 爬蟲函式 (已新增抓取主持人邏輯) ---
def scrape_single_page(url):
    try:
        response = requests.get(url, timeout=5)
        if response.status_code != 200: return [], False
        soup = BeautifulSoup(response.text, 'html.parser')
        items = soup.find_all(class_="calendar-item")
        if not items: return [], False

        page_events = []
        for item in items:
            title_el = item.find(class_="header-text")
            if not title_el: continue
            
            # 初始化字典 (包含所有需要的欄位)
            event_data = {
                "活動名稱": title_el.text.strip(),
                "時間": "", 
                "地點": "", 
                "主講人": "", 
                "主持人": "", # ✨ 新增欄位
                "詳細內容": "", 
                "圖片連結": ""
            }
            
            # 抓取 Info
            for label in item.find_all(class_="info-name"):
                val = label.find_next_sibling(class_="info-text")
                if not val: val = label.find_previous_sibling(class_="info-text")
                if val:
                    txt = val.text.strip()
                    if "時間" in label.text: event_data["時間"] = txt
                    elif "地點" in label.text: event_data["地點"] = txt
                    elif "主講" in label.text: event_data["主講人"] = txt
                    elif "主持" in label.text: event_data["主持人"] = txt # ✨ 抓取邏輯
            
            # 抓取詳細
            desc = item.find(class_="web-editor")
            if desc: event_data["詳細內容"] = desc.text.strip().replace('\n', ' ')
            
            # 抓取圖片
            img_box = item.find(class_="detail-picbox")
            if img_box and img_box.find('img'):
                 if 'src' in img_box.find('img').attrs:
                    event_data["圖片連結"] = img_box.find('img')['src']

            page_events.append(event_data)
        return page_events, True
    except: return [], False

# --- 初始化 Session State ---
if 'all_events' not in st.session_state:
    st.session_state.all_events = [] 
if 'selected_events' not in st.session_state:
    st.session_state.selected_events = [] 

# --- 介面區塊 A: 資料抓取 ---
with st.expander("🛠️ 資料來源設定 (點擊展開)", expanded=not bool(st.session_state.all_events)):
    if st.button("🚀 抓取書展全資料 (模擬快取模式)"):
        all_data = []
        progress = st.progress(0)
        status = st.empty()
        
        day_count = 0
        for date_str, date_id in DATE_MAP.items():
            page = 1
            # 為了測試，這裡仍設為抓前 2 頁，實際使用建議設 while True 並拿掉 break
            while page <= 2: 
                url = f"{BASE_URL}/{date_id}?page={page}"
                status.text(f"抓取中: {date_str} 第 {page} 頁...")
                evs, has_data = scrape_single_page(url)
                
                if has_data and evs:
                    for e in evs:
                        e['日期'] = date_str
                        s_dt, e_dt = parse_time_range(date_str, e['時間'])
                        e['start_dt'] = s_dt
                        e['end_dt'] = e_dt
                        e['id'] = str(hash(e['活動名稱'] + e['時間']))
                        
                    all_data.extend(evs)
                    page += 1
                    time.sleep(0.1)
                else:
                    break
            day_count += 1
            progress.progress(day_count / len(DATE_MAP))
            
        st.session_state.all_events = all_data
        status.success(f"抓取完成！共 {len(all_data)} 筆資料。")
        st.rerun()

# --- 介面區塊 B: 選取與預覽 ---
if st.session_state.all_events:
    df = pd.DataFrame(st.session_state.all_events)
    
    if 'prev_counts' not in st.session_state:
        st.session_state.prev_counts = {}
    if 'focus_date' not in st.session_state:
        st.session_state.focus_date = "2025-02-04" 

    col_list, col_cal = st.columns([0.6, 0.4])
    selected_ids = []
    current_counts = {}

    # --- 左側：勾選清單 ---
    with col_list:
        st.subheader("1. 勾選您想參加的活動")
        tabs = st.tabs(list(DATE_MAP.keys()))
        
        for i, tab in enumerate(tabs):
            date_key = list(DATE_MAP.keys())[i]
            clean_date_str = date_key.split(" ")[0]
            
            with tab:
                day_df = df[df['日期'] == date_key].copy()
                
                if day_df.empty:
                    st.info("尚無資料")
                    continue
                
                # 新增勾選欄位
                if "加入" not in day_df.columns:
                    day_df.insert(0, "加入", False)
                
                # ✨ 定義顯示欄位順序 (加入 -> 日期 -> 時間 -> 名稱...)
                # 注意：不在這裡面的欄位 (如 id, start_dt) 將會被自動隱藏
                desired_order = ["加入", "日期", "時間", "活動名稱", "地點", "主講人", "主持人"]
                
                # Data Editor 設定
                edited_df = st.data_editor(
                    day_df,
                    column_config={
                        "加入": st.column_config.CheckboxColumn("參加", default=False, width="small"),
                        "日期": st.column_config.TextColumn("日期", width="small"),
                        "時間": st.column_config.TextColumn("時間", width="medium"),
                        "活動名稱": st.column_config.TextColumn("活動名稱", width="large"),
                        "地點": st.column_config.TextColumn("地點", width="medium"),
                        "主講人": st.column_config.TextColumn("主講人", width="medium"),
                        "主持人": st.column_config.TextColumn("主持人", width="medium"),
                    },
                    column_order=desired_order, # ✨ 強制應用排序並隱藏其他欄位
                    hide_index=True,
                    key=f"editor_{i}" 
                )
                
                selected_rows = edited_df[edited_df["加入"] == True]
                
                # 自動偵測變動邏輯
                count = len(selected_rows)
                current_counts[date_key] = count
                prev = st.session_state.prev_counts.get(date_key, 0)
                
                if count != prev:
                    st.session_state.focus_date = clean_date_str
                
                if not selected_rows.empty:
                    selected_ids.extend(selected_rows['id'].tolist())

    st.session_state.prev_counts = current_counts

    # --- 右側：迷你日曆 ---
    with col_cal:
        st.subheader("2. 您的行程預覽")
        
        calendar_events = []
        final_selected_data = df[df['id'].isin(selected_ids)]
        
        # 日曆設定
        calendar_options = {
            "initialView": "timeGridDay",
            "initialDate": st.session_state.focus_date,
            "headerToolbar": {
                "left": "prev,next",
                "center": "title",
                # ✨ 新增 timeGridWeek 以支援週顯示
                "right": "timeGridWeek,timeGridDay,listDay"
            },
            "slotMinTime": "10:00:00",
            "slotMaxTime": "22:00:00",
            "height": "auto",
            "navLinks": True,
            "nowIndicator": True,
            "allDaySlot": False,
        }
        
        calendar_css = """
            .fc-event-title { font-size: 14px !important; font-weight: bold; }
            .fc-timegrid-slot { height: 40px !important; }
        """

        if not final_selected_data.empty:
            for _, row in final_selected_data.iterrows():
                if row['start_dt'] and row['end_dt']:
                    calendar_events.append({
                        "title": row['活動名稱'],
                        "start": row['start_dt'].isoformat(),
                        "end": row['end_dt'].isoformat(),
                        "backgroundColor": "#FF6C6C",
                        "borderColor": "#FF6C6C",
                    })
            
            calendar(
                events=calendar_events,
                options=calendar_options,
                custom_css=calendar_css,
                key=f"cal_{st.session_state.focus_date}"
            )
            
            # --- 匯出區塊 ---
            st.divider()
            st.subheader("3. 帶走您的行程 🎒")
            
            export_col1, export_col2, export_col3 = st.columns(3)
            
            # 1. ICS 下載
            with export_col1:
                c = Calendar()
                for _, row in final_selected_data.iterrows():
                    e = Event()
                    e.name = row['活動名稱']
                    e.begin = row['start_dt']
                    e.end = row['end_dt']
                    e.location = row['地點']
                    e.description = f"講者: {row['主講人']}\n主持人: {row['主持人']}\n\n{row['詳細內容']}"
                    c.events.add(e)
                
                st.download_button(
                    label="📅 同步手機\n(.ics)",
                    data=c.serialize(),
                    file_name="my_tibe_schedule.ics",
                    mime="text/calendar",
                )
                with st.expander("❓ 如何加入？"):
                    st.markdown("iPhone: 點擊下載 > 加入全部\nAndroid: 開啟檔案 > 儲存")

            # 2. Excel 下載 (加入主持人欄位)
            with export_col2:
                print_df = final_selected_data[['日期', '時間', '活動名稱', '地點', '主講人', '主持人']].sort_values(by=['日期', '時間'])
                csv = print_df.to_csv(index=False).encode('utf-8-sig')
                st.download_button(
                    label="🖨️ 列印清單\n(.csv)",
                    data=csv,
                    file_name="書展活動_print.csv",
                    mime="text/csv"
                )

            # 3. 文字懶人包 (加入主持人資訊)
            with export_col3:
                text_content = "📚 書展行程 📚\n"
                sorted_data = final_selected_data.sort_values(by=['日期', '時間'])
                curr_d = ""
                for _, row in sorted_data.iterrows():
                    if row['日期'] != curr_d:
                        text_content += f"\n📅 {row['日期']}\n----------\n"
                        curr_d = row['日期']
                    text_content += f"⏰ {row['時間']} | {row['活動名稱']}\n"
                    text_content += f"📍 {row['地點']} | 🗣️ {row['主講人']}\n"
                    if row['主持人']:
                         text_content += f"🎤 主持: {row['主持人']}\n"
                
                st.download_button(
                    label="💬 文字版\n(Line)",
                    data=text_content,
                    file_name="書展_line.txt",
                    mime="text/plain"
                )

        else:
            st.info("👈 請先在左側勾選活動")
            calendar(
                events=[], 
                options=calendar_options,
                custom_css=calendar_css,
                key="empty_calendar"
            )