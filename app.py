import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import datetime
from datetime import timedelta
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
# 🔥 關鍵修改：現在兩者都指向同一個 Google Sheet 檔案
SHEET_NAME_MASTER = "2026國際書展行事曆" # 讀取活動資料
SHEET_NAME_USER = "2026國際書展行事曆"   # 儲存使用者行程
WORKSHEETS_TO_LOAD = ["國際書展"]

# --- 初始化 Session State ---
if "calendar_focus_date" not in st.session_state: st.session_state.calendar_focus_date = "2026-02-04" 
if "prev_selection_counts" not in st.session_state: st.session_state.prev_selection_counts = {}
if "user_id" not in st.session_state: st.session_state.user_id = ""
if "user_pin" not in st.session_state: st.session_state.user_pin = ""
if "is_logged_in" not in st.session_state: st.session_state.is_logged_in = False
if "saved_ids" not in st.session_state: st.session_state.saved_ids = []

# --- 2. 連線與資料讀取 (公用資料) ---
@st.cache_data(ttl=300)
def load_master_data():
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
            spreadsheet = client.open(SHEET_NAME_MASTER)
        except gspread.SpreadsheetNotFound:
            return None, f"找不到檔案：{SHEET_NAME_MASTER}"

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
                
                # ID 生成
                df['id'] = df.apply(lambda x: f"{x['日期']}_{x['時間']}_{x['活動名稱']}", axis=1)
                
                all_frames.append(df)
            except Exception as e:
                # 把這行加回去，方便後台除錯
                print(f"Skipping {ws_name}: {e}")
                pass

        if not all_frames: return pd.DataFrame(), "無資料"
        final_df = pd.concat(all_frames, ignore_index=True)
        return final_df, "Success"

    except Exception as e:
        return None, str(e)

# --- 3. 使用者資料讀寫 (私用資料) ---
def connect_to_user_sheet():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    try:
        if "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
            if "private_key" in creds_dict:
                 creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name("secrets.json", scope)
        client = gspread.authorize(creds)
        # 這裡會開啟同一個檔案
        spreadsheet = client.open(SHEET_NAME_USER)
        return spreadsheet
    except:
        return None

def get_user_schedule_sheet(spreadsheet, user_id, pin_code):
    """
    取得使用者的行程分頁 (命名為: ID_行程)
    """
    safe_id = re.sub(r'[^a-zA-Z0-9_\u4e00-\u9fa5]', '', str(user_id))
    sheet_title = f"{safe_id}_行程" 
    
    try:
        sheet = spreadsheet.worksheet(sheet_title)
        return sheet, "Success"
    except gspread.WorksheetNotFound:
        try:
            # 建立新分頁
            sheet = spreadsheet.add_worksheet(title=sheet_title, rows=100, cols=10)
            headers = ["id", "日期", "時間", "活動名稱", "地點"] # 只存關鍵資料
            sheet.update(range_name='A1', values=[headers])
            return sheet, "Success"
        except Exception as e:
            return None, f"建立失敗: {e}"

def load_user_saved_ids(user_id, pin_code):
    """讀取使用者已儲存的活動 ID"""
    ss = connect_to_user_sheet()
    if not ss: return []
    
    sheet, msg = get_user_schedule_sheet(ss, user_id, pin_code)
    if not sheet: return []
    
    try:
        data = sheet.get_all_values()
        if len(data) < 2: return []
        df = pd.DataFrame(data[1:], columns=data[0])
        if 'id' in df.columns:
            return df['id'].tolist()
        return []
    except:
        return []

def save_user_schedule_to_cloud(user_id, pin_code, selected_df):
    """將目前的勾選清單存回雲端"""
    ss = connect_to_user_sheet()
    if not ss: return False, "連線失敗"
    
    sheet, msg = get_user_schedule_sheet(ss, user_id, pin_code)
    if not sheet: return False, msg
    
    try:
        # 只存關鍵欄位，節省空間
        save_cols = ["id", "日期", "時間", "活動名稱", "地點"]
        valid_cols = [c for c in save_cols if c in selected_df.columns]
        df_to_save = selected_df[valid_cols]
        
        # 轉成 List
        data = [df_to_save.columns.values.tolist()] + df_to_save.values.tolist()
        
        sheet.clear()
        sheet.update(range_name='A1', values=data)
        return True, "儲存成功"
    except Exception as e:
        return False, str(e)

# --- 時間解析工具 ---
def parse_datetime_range(date_str, time_str):
    try:
        clean_date = str(date_str).split(" ")[0].strip()
        clean_time = str(time_str).replace("：", ":").replace("~", "-").replace(" ", "")
        
        if "-" in clean_time:
            parts = clean_time.split("-")
            start_t = parts[0]
            end_t = parts[1]
        else:
            start_t = clean_time
            end_t = clean_time 
        
        start_dt_str = f"{clean_date} {start_t}"
        end_dt_str = f"{clean_date} {end_t}"
        
        fmt = "%Y-%m-%d %H:%M"
        try:
            start_dt = datetime.datetime.strptime(start_dt_str, fmt)
            end_dt = datetime.datetime.strptime(end_dt_str, fmt)
        except ValueError:
            fmt_sec = "%Y-%m-%d %H:%M:%S"
            try:
                start_dt = datetime.datetime.strptime(start_dt_str, fmt_sec)
                end_dt = datetime.datetime.strptime(end_dt_str, fmt_sec)
            except:
                return None, None
        
        return start_dt, end_dt
    except:
        return None, None

# --- 主程式介面 ---

# 1. 登入檢查
if not st.session_state.is_logged_in:
    st.title("📅 2026 書展排程神器")
    st.info("請先登入，系統將為您自動讀取並儲存專屬行程！")
    
    with st.sidebar.form("login_form"):
        st.header("🔐 用戶登入")
        input_id = st.text_input("👤 暱稱", placeholder="例如: Kevin")
        input_pin = st.text_input("🔑 密碼 (PIN)", type="password", placeholder="例如: 0000")
        if st.form_submit_button("🚀 登入 / 註冊"):
            if input_id and input_pin:
                # 嘗試讀取雲端存檔
                with st.spinner("正在讀取您的雲端行程..."):
                    saved_ids = load_user_saved_ids(input_id, input_pin)
                    st.session_state.saved_ids = saved_ids
                    st.session_state.user_id = input_id
                    st.session_state.user_pin = input_pin
                    st.session_state.is_logged_in = True
                st.rerun()
            else:
                st.sidebar.error("請輸入暱稱與密碼")
    st.stop() 

# 2. 登入後介面
st.sidebar.success(f"Hi, {st.session_state.user_id}")

# 讀取 Master 資料
raw_df, msg = load_master_data()

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

# --- 側邊欄功能區 ---
if st.sidebar.button("🚪 登出"):
    st.session_state.is_logged_in = False
    st.session_state.user_id = ""
    st.session_state.saved_ids = []
    st.rerun()

# --- 全域變數：勾選 ID ---
all_selected_ids = []
current_selection_counts = {}

# ==========================================
# 區塊 1：活動清單與勾選 (上方)
# ==========================================
st.title("📅 2026 書展排程神器")
st.markdown("上方勾選活動，下方即時預覽週曆！")

st.subheader("1. 勾選活動 ✅")

# 篩選器
with st.expander("🔎 進階篩選 (地點/類型)", expanded=False):
    c_filter1, c_filter2, c_filter3 = st.columns(3)
    with c_filter1:
        f_loc = st.multiselect("地點", options=sorted(list(set(proc_df['地點'].astype(str)))))
    with c_filter2:
        f_type = st.multiselect("類型", options=sorted(list(set(proc_df['類型'].astype(str)))))
    with c_filter3:
        f_key = st.text_input("關鍵字搜尋 (活動/講者)")

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
            
            # 雲端狀態自動勾選
            if "參加" not in day_df.columns:
                day_df.insert(0, "參加", day_df['id'].isin(st.session_state.saved_ids))
            
            edited_day_df = st.data_editor(
                day_df,
                column_config={
                    "參加": st.column_config.CheckboxColumn("參加", width="small"),
                    "時間": st.column_config.TextColumn("時間", width="small"),
                    "活動名稱": st.column_config.TextColumn("活動名稱", width="large"),
                    "地點": st.column_config.TextColumn("地點", width="medium"),
                    "主講人": st.column_config.TextColumn("主講人", width="medium"),
                    "類型": None, "主持人": None, "詳細內容": None, "備註": None, "來源": None, 
                    "id": None, "start_dt": None, "end_dt": None, "日期": None
                },
                hide_index=True,
                key=f"editor_{date_str}"
            )
            
            selected_rows = edited_day_df[edited_day_df["參加"] == True]
            
            # 自動跳轉邏輯
            current_count = len(selected_rows)
            current_selection_counts[date_str] = current_count
            prev_count = st.session_state.prev_selection_counts.get(date_str, 0)
            
            if current_count != prev_count:
                st.session_state.calendar_focus_date = date_str
            
            if not selected_rows.empty:
                all_selected_ids.extend(selected_rows['id'].tolist())

st.session_state.prev_selection_counts = current_selection_counts

st.markdown("---")

# ==========================================
# 區塊 2：行程預覽日曆 (下方)
# ==========================================
st.subheader("2. 行程週曆 🗓️")

final_selected = proc_df[
    (proc_df['id'].isin(all_selected_ids)) & 
    (proc_df['start_dt'].notnull())
]

c_cal_head, c_cal_save = st.columns([0.8, 0.2])
with c_cal_head:
    if len(final_selected) > 0:
        st.success(f"已顯示 {len(final_selected)} 場活動")
with c_cal_save:
    # 儲存到雲端按鈕
    if st.button("💾 儲存到雲端", type="primary", use_container_width=True):
        with st.spinner("正在同步資料..."):
            success, s_msg = save_user_schedule_to_cloud(
                st.session_state.user_id, 
                st.session_state.user_pin, 
                final_selected
            )
            if success:
                st.toast("✅ 儲存成功！下次登入會自動讀取。")
                st.session_state.saved_ids = final_selected['id'].tolist()
            else:
                st.error(f"儲存失敗: {s_msg}")

cal_events = []
for _, row in final_selected.iterrows():
    bg_color = "#3788d8"
    if str(row['來源']) != "國際書展": bg_color = "#ff9f43"
    
    event_title = f"{row['活動名稱']} @ {row['地點']}"
    
    cal_events.append({
        "title": event_title,
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
        "left": "prev,next today",
        "center": "title",
        "right": "timeGridWeek,timeGridDay,listDay" 
    },
    "slotMinTime": "09:00:00",
    "slotMaxTime": "21:00:00",
    "height": "650px", 
    "nowIndicator": True
}

calendar(events=cal_events, options=calendar_options, key=f"main_calendar_{initial_view_date}")

st.markdown("---")

# ==========================================
# 區塊 3：匯出功能 (底部)
# ==========================================
st.subheader("3. 帶走行程 🎒")

if final_selected.empty:
    st.info("👈 請先在上方勾選活動，這裡才會出現匯出按鈕喔！")
else:
    c1, c2, c3 = st.columns(3)
    
    # 1. ICS
    with c1:
        cal_obj = Calendar()
        for _, row in final_selected.iterrows():
            e = Event()
            e.name = f"{row['活動名稱']} ({row['地點']})"
            
            if row['start_dt']: e.begin = row['start_dt'] - timedelta(hours=8)
            if row['end_dt']: e.end = row['end_dt'] - timedelta(hours=8)
                
            e.location = str(row['地點'])
            
            desc_parts = []
            if row['主講人']: desc_parts.append(f"👨‍🏫 主講: {row['主講人']}")
            if row['主持人']: desc_parts.append(f"🎤 主持: {row['主持人']}")
            
            note = str(row['備註']).strip()
            detail = str(row['詳細內容']).strip()
            
            if detail:
                desc_parts.append(f"\n📝 內容:\n{detail}")
            elif note:
                desc_parts.append(f"\n📝 備註: {note}")
            
            e.description = "\n".join(desc_parts)
            cal_obj.events.add(e)
        
        st.download_button("📅 匯出手機行事曆 (.ics)", data=cal_obj.serialize(), file_name="tibe_2026.ics", mime="text/calendar")

    # 2. CSV
    with c2:
        out_cols = ["日期", "時間", "活動名稱", "地點", "主講人", "主持人", "備註"]
        valid_cols = [c for c in out_cols if c in final_selected.columns]
        csv_data = final_selected[valid_cols].to_csv(index=False).encode('utf-8-sig')
        st.download_button("🖨️ 匯出表格 (.csv)", data=csv_data, file_name="tibe_2026_schedule.csv", mime="text/csv")

    # 3. Text
    with c3:
        txt_out = "📚 2026 書展行程表 📚\n"
        sorted_rows = final_selected.sort_values(by=['日期', '時間'])
        curr_date = ""
        for _, row in sorted_rows.iterrows():
            if row['日期'] != curr_date:
                txt_out += f"\n📅 {row['日期']}\n" + "-"*20 + "\n"
                curr_date = row['日期']
            txt_out += f"{row['時間']} | {row['活動名稱']}\n"
            txt_out += f"📍 {row['地點']}"
            if row['主講人']: txt_out += f" | 🗣️ {row['主講人']}"
            txt_out += "\n\n"
        
        st.download_button("💬 複製文字行程", data=txt_out, file_name="tibe_text.txt", mime="text/plain")