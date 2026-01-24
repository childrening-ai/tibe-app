import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import datetime
from streamlit_calendar import calendar
from ics import Calendar, Event
import time
import re

# 1. 頁面基本設定
st.set_page_config(
    page_title="2026 書展排程神器",
    page_icon="📅",
    layout="wide"
)

# --- 設定區 ---
SHEET_NAME = "2026國際書展行事曆"
# 這裡可以填入多個分頁名稱，例如 ["國際書展", "親子天下"]
WORKSHEETS_TO_LOAD = ["國際書展"]

# --- 2. 連線與資料讀取 ---
@st.cache_data(ttl=300)
def load_sheet_data():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    try:
        # 讀取 Secrets
        if "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
            if "private_key" in creds_dict:
                 creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name("secrets.json", scope)
        
        client = gspread.authorize(creds)
        
        try:
            spreadsheet = client.open(SHEET_NAME)
        except gspread.SpreadsheetNotFound:
            return None, f"找不到檔案：{SHEET_NAME}"

        all_frames = []
        for ws_name in WORKSHEETS_TO_LOAD:
            try:
                worksheet = spreadsheet.worksheet(ws_name)
                data = worksheet.get_all_values()
                if len(data) < 2: continue
                
                df = pd.DataFrame(data[1:], columns=data[0])
                df['來源'] = ws_name 
                df.columns = [c.strip() for c in df.columns]
                
                # 產生唯一 ID (為了追蹤勾選狀態)
                # 使用雜湊值確保唯一性
                df['id'] = df.apply(lambda x: str(hash(x['日期'] + x['時間'] + x['活動名稱'])), axis=1)
                
                all_frames.append(df)
            except:
                pass

        if not all_frames: return pd.DataFrame(), "無資料"
        
        final_df = pd.concat(all_frames, ignore_index=True)
        return final_df, "Success"

    except Exception as e:
        return None, str(e)

# --- 時間解析工具 (給日曆用) ---
def parse_datetime_range(date_str, time_str):
    """
    將 '2026-02-04' 和 '10:00 - 11:00' 轉換成 datetime 物件
    """
    try:
        # 清理日期 (只取前段，預防有括號)
        clean_date = date_str.split(" ")[0] 
        
        # 清理時間 (處理全形符號或不同分隔符)
        clean_time = time_str.replace("：", ":").replace("~", "-").replace(" ", "")
        
        if "-" in clean_time:
            start_t, end_t = clean_time.split("-")
        else:
            # 如果只有一個時間，預設活動一小時
            start_t = clean_time
            end_t = clean_time # 暫時防爆
            
        start_dt_str = f"{clean_date} {start_t}"
        end_dt_str = f"{clean_date} {end_t}"
        
        # 嘗試解析
        fmt = "%Y-%m-%d%H:%M"
        start_dt = datetime.datetime.strptime(start_dt_str, fmt)
        end_dt = datetime.datetime.strptime(end_dt_str, fmt)
        
        return start_dt, end_dt
    except:
        return None, None

# --- 主程式 ---

st.title("📅 2026 書展排程神器")
st.markdown("左側勾選活動，右側即時預覽行程！支援 **匯出手機行事曆**。")

# 讀取資料
raw_df, msg = load_sheet_data()

if raw_df is None or raw_df.empty:
    st.error(f"⚠️ 資料讀取失敗或無資料：{msg}")
    st.stop()

# 預處理：產生 datetime 欄位 (為了日曆顯示)
# 我們不直接改原始 df，而是建立一個處理過的版本
proc_df = raw_df.copy()
start_list, end_list = [], []

for _, row in proc_df.iterrows():
    s, e = parse_datetime_range(row['日期'], row['時間'])
    start_list.append(s)
    end_list.append(e)

proc_df['start_dt'] = start_list
proc_df['end_dt'] = end_list

# --- 版面配置 ---
col_list, col_cal = st.columns([0.6, 0.4])

# 用來收集所有被勾選的 ID
all_selected_ids = []

# --- 左側：活動清單 (含篩選) ---
with col_list:
    st.subheader("1. 勾選活動 ✅")
    
    # 篩選器
    with st.expander("🔎 進階篩選 (地點/類型)", expanded=False):
        f_loc = st.multiselect("地點", options=sorted(list(set(proc_df['地點'].astype(str)))))
        f_type = st.multiselect("類型", options=sorted(list(set(proc_df['類型'].astype(str)))))
        f_key = st.text_input("關鍵字搜尋")

    # 執行篩選
    mask = [True] * len(proc_df)
    if f_loc: mask &= proc_df['地點'].isin(f_loc)
    if f_type: mask &= proc_df['類型'].isin(f_type)
    if f_key: mask &= (proc_df['活動名稱'].str.contains(f_key, case=False) | proc_df['講者'].str.contains(f_key, case=False))
    
    filtered_df = proc_df[mask]
    
    # 依日期分頁
    unique_dates = sorted(list(set(filtered_df['日期'].unique())))
    
    if not unique_dates:
        st.info("沒有符合條件的活動")
    else:
        tabs = st.tabs([d[5:] for d in unique_dates]) # 只顯示 MM-DD
        
        for i, date_str in enumerate(unique_dates):
            with tabs[i]:
                # 取出當日資料
                day_df = filtered_df[filtered_df['日期'] == date_str].copy()
                
                # 排序
                day_df = day_df.sort_values(by='時間')
                
                # 加入 "參加" 勾選欄位 (預設 False)
                if "參加" not in day_df.columns:
                    day_df.insert(0, "參加", False)
                
                # 使用 Data Editor 讓使用者勾選
                # key 非常重要，必須包含日期，否則切換 tab 會亂掉
                edited_day_df = st.data_editor(
                    day_df,
                    column_config={
                        "參加": st.column_config.CheckboxColumn("參加", width="small"),
                        "時間": st.column_config.TextColumn("時間", width="medium"),
                        "活動名稱": st.column_config.TextColumn("活動名稱", width="large"),
                        "地點": st.column_config.TextColumn("地點", width="medium"),
                        "類型": st.column_config.TextColumn("類型", width="small"),
                        "來源": st.column_config.TextColumn("來源", width="small"),
                        # 隱藏不想顯示的技術欄位
                        "id": None, "start_dt": None, "end_dt": None, "日期": None, "備註": None, "詳細內容": None
                    },
                    hide_index=True,
                    key=f"editor_{date_str}"
                )
                
                # 收集被勾選的 Rows
                selected_rows = edited_day_df[edited_day_df["參加"] == True]
                if not selected_rows.empty:
                    all_selected_ids.extend(selected_rows['id'].tolist())

# --- 右側：迷你日曆 & 匯出 ---
with col_cal:
    st.subheader("2. 行程預覽 🗓️")
    
    # 撈出所有被勾選的資料
    final_selected = proc_df[proc_df['id'].isin(all_selected_ids)]
    
    # 準備 Calendar 事件格式
    cal_events = []
    if not final_selected.empty:
        for _, row in final_selected.iterrows():
            if row['start_dt'] and row['end_dt']:
                # 根據來源給不同顏色
                bg_color = "#3788d8" # 預設藍
                if row['來源'] != "國際書展": bg_color = "#ff9f43" # 其他來源用橘色
                
                cal_events.append({
                    "title": row['活動名稱'],
                    "start": row['start_dt'].isoformat(),
                    "end": row['end_dt'].isoformat(),
                    "backgroundColor": bg_color,
                    "borderColor": bg_color
                })
        
        # 設定預設顯示日期 (跳轉到第一個活動的日期)
        initial_date = sorted(final_selected['日期'].tolist())[0]
    else:
        initial_date = datetime.date.today().strftime("%Y-%m-%d")

    # 顯示日曆
    calendar_options = {
        "initialView": "timeGridDay",
        "initialDate": initial_date,
        "headerToolbar": {
            "left": "prev,next",
            "center": "title",
            "right": "timeGridDay,listDay"
        },
        "slotMinTime": "09:00:00",
        "slotMaxTime": "21:00:00",
        "height": "auto",
        "nowIndicator": True
    }
    
    calendar(events=cal_events, options=calendar_options, key="main_calendar")
    
    # --- 3. 匯出功能 ---
    st.divider()
    st.subheader("3. 帶走行程 🎒")
    
    if final_selected.empty:
        st.caption("👈 請先在左側勾選活動，才能匯出喔！")
    else:
        c1, c2, c3 = st.columns(3)
        
        # 1. ICS 手機行事曆
        with c1:
            cal_obj = Calendar()
            for _, row in final_selected.iterrows():
                e = Event()
                e.name = f"{row['活動名稱']} ({row['地點']})"
                if row['start_dt']: e.begin = row['start_dt']
                if row['end_dt']: e.end = row['end_dt']
                e.location = row['地點']
                e.description = f"講者: {row['講者']}\n備註: {row['備註']}"
                cal_obj.events.add(e)
            
            st.download_button(
                "📅 手機行事曆",
                data=cal_obj.serialize(),
                file_name="tibe_2026.ics",
                mime="text/calendar",
                help="下載後點擊檔案，即可匯入 iPhone/Android 行事曆"
            )

        # 2. Excel/CSV
        with c2:
            csv_data = final_selected[['日期', '時間', '活動名稱', '地點', '講者', '備註']].to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                "🖨️ 列印用表格",
                data=csv_data,
                file_name="tibe_2026_schedule.csv",
                mime="text/csv"
            )

        # 3. 文字懶人包
        with c3:
            txt_out = "📚 2026 書展行程表 📚\n"
            sorted_rows = final_selected.sort_values(by=['日期', '時間'])
            curr_date = ""
            for _, row in sorted_rows.iterrows():
                if row['日期'] != curr_date:
                    txt_out += f"\n📅 {row['日期']}\n" + "-"*15 + "\n"
                    curr_date = row['日期']
                txt_out += f"{row['時間']} | {row['活動名稱']}\n"
                txt_out += f"📍 {row['地點']}\n\n"
            
            st.download_button(
                "💬 文字懶人包",
                data=txt_out,
                file_name="tibe_text.txt",
                mime="text/plain"
            )