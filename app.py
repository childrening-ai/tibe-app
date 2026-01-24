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
WORKSHEETS_TO_LOAD = ["國際書展"]

# --- 初始化 Session State ---
if "calendar_focus_date" not in st.session_state:
    st.session_state.calendar_focus_date = "2026-02-04" 

if "prev_selection_counts" not in st.session_state:
    st.session_state.prev_selection_counts = {}

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
        STANDARD_COLS = ["日期", "時間", "活動名稱", "地點", "主講人", "主持人", "類型", "備註", "詳細內容"]

        for ws_name in WORKSHEETS_TO_LOAD:
            try:
                worksheet = spreadsheet.worksheet(ws_name)
                data = worksheet.get_all_values()
                if len(data) < 2: continue
                
                df = pd.DataFrame(data[1:], columns=data[0])
                df['來源'] = ws_name 
                df.columns = [c.strip() for c in df.columns]
                
                if "主講人" not in df.columns and "講者" in df.columns:
                    df.rename(columns={"講者": "主講人"}, inplace=True)

                for col in STANDARD_COLS:
                    if col not in df.columns:
                        df[col] = "" 
                
                df = df.fillna("")
                
                # 🔥 修正 ID 生成：改用純字串拼接，比 hash 更穩定
                df['id'] = df.apply(lambda x: f"{x['日期']}_{x['時間']}_{x['活動名稱']}", axis=1)
                
                all_frames.append(df)
            except Exception as e:
                print(f"Skipping {ws_name}: {e}")
                pass

        if not all_frames: return pd.DataFrame(), "無資料"
        final_df = pd.concat(all_frames, ignore_index=True)
        return final_df, "Success"

    except Exception as e:
        return None, str(e)

# --- 🔥 修正版：時間解析工具 ---
def parse_datetime_range(date_str, time_str):
    try:
        clean_date = str(date_str).split(" ")[0].strip()
        # 清理時間字串
        clean_time = str(time_str).replace("：", ":").replace("~", "-").replace(" ", "")
        
        if "-" in clean_time:
            parts = clean_time.split("-")
            start_t = parts[0]
            end_t = parts[1]
        else:
            start_t = clean_time
            end_t = clean_time 
        
        # 簡單補救：如果時間只有 "14:00"，補上秒數變成 "14:00:00" 比較保險，或者依格式判斷
        # 這裡假設格式是 HH:MM
        
        start_dt_str = f"{clean_date} {start_t}"
        end_dt_str = f"{clean_date} {end_t}"
        
        # 🔥 修正處：這裡補上了一個空白，對應 f-string 裡的空白
        fmt = "%Y-%m-%d %H:%M" 
        
        try:
            start_dt = datetime.datetime.strptime(start_dt_str, fmt)
            end_dt = datetime.datetime.strptime(end_dt_str, fmt)
        except ValueError:
            # 如果解析失敗，試試看有沒有秒數
            fmt_sec = "%Y-%m-%d %H:%M:%S"
            try:
                start_dt = datetime.datetime.strptime(start_dt_str, fmt_sec)
                end_dt = datetime.datetime.strptime(end_dt_str, fmt_sec)
            except:
                return None, None
        
        return start_dt, end_dt
    except:
        return None, None

# --- 主程式 ---

st.title("📅 2026 書展排程神器")
st.markdown("左側勾選活動，右側即時預覽行程！(支援 **匯出手機行事曆**)")

# 讀取資料
raw_df, msg = load_sheet_data()

if raw_df is None or raw_df.empty:
    st.error(f"⚠️ 資料讀取失敗：{msg}")
    st.stop()

# 預處理
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
all_selected_ids = []
current_selection_counts = {}

# --- 左側：活動清單 ---
with col_list:
    st.subheader("1. 勾選活動 ✅")
    
    with st.expander("🔎 進階篩選", expanded=False):
        f_loc = st.multiselect("地點", options=sorted(list(set(proc_df['地點'].astype(str)))))
        f_type = st.multiselect("類型", options=sorted(list(set(proc_df['類型'].astype(str)))))
        f_key = st.text_input("關鍵字搜尋")

    mask = [True] * len(proc_df)
    if f_loc: mask &= proc_df['地點'].isin(f_loc)
    if f_type: mask &= proc_df['類型'].isin(f_type)
    if f_key: 
        mask &= (
            proc_df['活動名稱'].str.contains(f_key, case=False) | 
            proc_df['主講人'].str.contains(f_key, case=False) |
            proc_df['主持人'].str.contains(f_key, case=False)
        )
    
    filtered_df = proc_df[mask]
    unique_dates = sorted(list(set(filtered_df['日期'].unique())))
    
    if not unique_dates:
        st.info("沒有符合條件的活動")
    else:
        tab_names = [d[5:] if len(str(d))>5 else str(d) for d in unique_dates]
        tabs = st.tabs(tab_names)
        
        for i, date_str in enumerate(unique_dates):
            with tabs[i]:
                day_df = filtered_df[filtered_df['日期'] == date_str].copy()
                day_df = day_df.sort_values(by='時間')
                
                if "參加" not in day_df.columns:
                    day_df.insert(0, "參加", False)
                
                edited_day_df = st.data_editor(
                    day_df,
                    column_config={
                        "參加": st.column_config.CheckboxColumn("參加", width="small"),
                        "時間": st.column_config.TextColumn("時間", width="medium"),
                        "活動名稱": st.column_config.TextColumn("活動名稱", width="large"),
                        "地點": st.column_config.TextColumn("地點", width="medium"),
                        "主講人": st.column_config.TextColumn("主講人", width="medium"),
                        "類型": st.column_config.TextColumn("類型", width="small"),
                        "主持人": None, "詳細內容": None, "備註": None, "來源": None, 
                        "id": None, "start_dt": None, "end_dt": None, "日期": None
                    },
                    hide_index=True,
                    key=f"editor_{date_str}"
                )
                
                selected_rows = edited_day_df[edited_day_df["參加"] == True]
                
                # 自動跳轉日曆邏輯
                current_count = len(selected_rows)
                current_selection_counts[date_str] = current_count
                prev_count = st.session_state.prev_selection_counts.get(date_str, 0)
                
                if current_count != prev_count:
                    st.session_state.calendar_focus_date = date_str
                
                if not selected_rows.empty:
                    all_selected_ids.extend(selected_rows['id'].tolist())

    st.session_state.prev_selection_counts = current_selection_counts

# --- 右側：日曆 & 匯出 ---
with col_cal:
    st.subheader("2. 行程預覽 🗓️")
    
    # 這裡過濾出「被勾選」且「時間解析成功」的資料
    final_selected = proc_df[
        (proc_df['id'].isin(all_selected_ids)) & 
        (proc_df['start_dt'].notnull()) # 確保時間有效
    ]
    
    # Debug 訊息：告訴使用者到底抓到了幾筆
    if len(all_selected_ids) > 0 and len(final_selected) == 0:
        st.warning(f"⚠️ 您勾選了 {len(all_selected_ids)} 筆，但時間格式似乎都無法解析，無法顯示在日曆上。")
    elif len(final_selected) > 0:
        st.success(f"已顯示 {len(final_selected)} 場活動")

    cal_events = []
    for _, row in final_selected.iterrows():
        bg_color = "#3788d8"
        if str(row['來源']) != "國際書展": bg_color = "#ff9f43"
        
        cal_events.append({
            "title": row['活動名稱'],
            "start": row['start_dt'].isoformat(),
            "end": row['end_dt'].isoformat(),
            "backgroundColor": bg_color,
            "borderColor": bg_color
        })

    initial_view_date = st.session_state.calendar_focus_date

    calendar_options = {
        "initialView": "timeGridDay",
        "initialDate": initial_view_date,
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
    
    calendar(events=cal_events, options=calendar_options, key=f"main_calendar_{initial_view_date}")
    
    st.divider()
    st.subheader("3. 帶走行程 🎒")
    
    if final_selected.empty:
        st.caption("👈 請先勾選活動")
    else:
        c1, c2, c3 = st.columns(3)
        
        # 1. ICS
        with c1:
            cal_obj = Calendar()
            for _, row in final_selected.iterrows():
                e = Event()
                e.name = f"{row['活動名稱']} ({row['地點']})"
                if row['start_dt']: e.begin = row['start_dt']
                if row['end_dt']: e.end = row['end_dt']
                e.location = str(row['地點'])
                
                desc_parts = []
                if row['主講人']: desc_parts.append(f"主講: {row['主講人']}")
                if row['主持人']: desc_parts.append(f"主持: {row['主持人']}")
                if row['備註']: desc_parts.append(f"備註: {row['備註']}")
                if row['詳細內容']: desc_parts.append(f"\n{row['詳細內容']}")
                
                e.description = "\n".join(desc_parts)
                cal_obj.events.add(e)
            
            st.download_button("📅 手機行事曆", data=cal_obj.serialize(), file_name="tibe_2026.ics", mime="text/calendar")

        # 2. CSV
        with c2:
            out_cols = ["日期", "時間", "活動名稱", "地點", "主講人", "主持人", "備註", "詳細內容"]
            valid_cols = [c for c in out_cols if c in final_selected.columns]
            csv_data = final_selected[valid_cols].to_csv(index=False).encode('utf-8-sig')
            st.download_button("🖨️ 列印用表格", data=csv_data, file_name="tibe_2026_schedule.csv", mime="text/csv")

        # 3. Text
        with c3:
            txt_out = "📚 2026 書展行程表 📚\n"
            sorted_rows = final_selected.sort_values(by=['日期', '時間'])
            curr_date = ""
            for _, row in sorted_rows.iterrows():
                if row['日期'] != curr_date:
                    txt_out += f"\n📅 {row['日期']}\n" + "-"*15 + "\n"
                    curr_date = row['日期']
                txt_out += f"{row['時間']} | {row['活動名稱']}\n"
                txt_out += f"📍 {row['地點']}"
                if row['主講人']: txt_out += f" | 🗣️ {row['主講人']}"
                txt_out += "\n"
            
            st.download_button("💬 文字懶人包", data=txt_out, file_name="tibe_text.txt", mime="text/plain")