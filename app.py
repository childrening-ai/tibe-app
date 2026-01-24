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

# 1. 頁面基本設定 (UI 優化：設定 layout 為 wide)
st.set_page_config(
    page_title="2026 書展排程神器",
    page_icon="📅",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- UI 美化 CSS ---
# 去除 Streamlit 預設的上方大量空白，讓手機版面更緊湊
st.markdown("""
    <style>
        .block-container {
            padding-top: 1rem !important;
            padding-bottom: 2rem !important;
        }
        /* 調整手機上的標題大小 */
        h1 { font-size: 1.8rem !important; }
        /* 隱藏預設的 footer */
        footer {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

# --- 設定區 ---
SHEET_NAME_MASTER = "2026國際書展行事曆" # 公用活動資料 (讀取用)
WORKSHEETS_TO_LOAD = ["國際書展"]

# 🔥 關鍵修改：使用者資料夾 ID (策略 A：一用戶一檔案)
# 您的資料夾: https://drive.google.com/drive/u/0/folders/1s1RvDbNaEIhkybxknvIRknzFWlI-1NA0
USER_DATA_FOLDER_ID = "1s1RvDbNaEIhkybxknvIRknzFWlI-1NA0" 

# --- 初始化 Session State ---
if "calendar_focus_date" not in st.session_state: st.session_state.calendar_focus_date = "2026-02-04" 
if "prev_selection_counts" not in st.session_state: st.session_state.prev_selection_counts = {}
if "user_id" not in st.session_state: st.session_state.user_id = ""
if "user_pin" not in st.session_state: st.session_state.user_pin = ""
if "is_logged_in" not in st.session_state: st.session_state.is_logged_in = False
if "is_guest" not in st.session_state: st.session_state.is_guest = False # 新增訪客狀態
if "saved_ids" not in st.session_state: st.session_state.saved_ids = []

# --- 連線功能 (GSpread Client) ---
def get_gspread_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    try:
        if "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
            if "private_key" in creds_dict:
                 creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name("secrets.json", scope)
        return gspread.authorize(creds)
    except:
        return None

# --- 2. 資料讀取 (公用資料) ---
@st.cache_data(ttl=300)
def load_master_data():
    client = get_gspread_client()
    if not client: return None, "連線失敗"

    try:
        spreadsheet = client.open(SHEET_NAME_MASTER)
        
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
                    if col not in df.columns: df[col] = "" 
                
                df = df.fillna("")
                df['id'] = df.apply(lambda x: f"{x['日期']}_{x['時間']}_{x['活動名稱']}", axis=1)
                all_frames.append(df)
            except Exception as e:
                print(f"Skipping {ws_name}: {e}") # 保留除錯訊息
                pass

        if not all_frames: return pd.DataFrame(), "無資料"
        final_df = pd.concat(all_frames, ignore_index=True)
        return final_df, "Success"

    except Exception as e:
        return None, str(e)

# --- 3. 使用者資料存取 (策略 A：獨立檔案) ---
def get_user_storage_file(client, user_id):
    """
    在指定資料夾中尋找或建立使用者的獨立 Spreadsheet
    檔名格式: 2026_TIBE_{user_id}
    """
    # 移除特殊字元，確保檔名合法
    safe_id = re.sub(r'[^a-zA-Z0-9_\u4e00-\u9fa5]', '', str(user_id))
    filename = f"2026_TIBE_{safe_id}"
    
    try:
        # 1. 嘗試直接開啟 (如果檔案已存在)
        sh = client.open(filename)
        return sh, "Existing"
    except gspread.SpreadsheetNotFound:
        # 2. 如果找不到，則在指定資料夾建立新檔案
        try:
            # 注意：這裡使用 folder_id 參數將檔案建在特定資料夾
            sh = client.create(filename, folder_id=USER_DATA_FOLDER_ID)
            
            # 初始化標題列
            sh.sheet1.update(range_name='A1', values=[["id", "日期", "時間", "活動名稱", "地點"]])
            return sh, "Created"
        except Exception as e:
            return None, f"建立檔案失敗: {e}"

def load_user_saved_ids(user_id):
    """讀取使用者雲端檔案中的 ID"""
    client = get_gspread_client()
    if not client: return []
    
    sh, status = get_user_storage_file(client, user_id)
    if not sh: return []
    
    try:
        worksheet = sh.sheet1
        data = worksheet.get_all_values()
        if len(data) < 2: return []
        
        df = pd.DataFrame(data[1:], columns=data[0])
        if 'id' in df.columns:
            return df['id'].tolist()
        return []
    except:
        return []

def save_user_schedule_to_cloud(user_id, selected_df):
    """將目前的勾選清單存回使用者的獨立檔案"""
    client = get_gspread_client()
    if not client: return False, "連線失敗"
    
    sh, status = get_user_storage_file(client, user_id)
    if not sh: return False, f"無法存取雲端檔案: {status}"
    
    try:
        worksheet = sh.sheet1
        
        save_cols = ["id", "日期", "時間", "活動名稱", "地點"]
        valid_cols = [c for c in save_cols if c in selected_df.columns]
        df_to_save = selected_df[valid_cols]
        
        data = [df_to_save.columns.values.tolist()] + df_to_save.values.tolist()
        
        worksheet.clear()
        worksheet.update(range_name='A1', values=data)
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

# ==========================================
# 登入頁面 (含訪客模式)
# ==========================================
if not st.session_state.is_logged_in:
    st.title("📅 2026 書展排程神器")
    
    # 兩欄佈局：左邊介紹，右邊登入框
    intro_col, login_col = st.columns([0.6, 0.4])
    
    with intro_col:
        st.markdown("""
        ### 歡迎使用！
        這是專為書展設計的排程小幫手。
        
        **功能特色：**
        * ✅ **一鍵篩選**：依地點、類型快速找活動
        * ✅ **自動排程**：勾選活動，自動生成週曆
        * ✅ **雲端同步**：登入後可儲存您的專屬行程 (換手機也能看)
        * ✅ **離線帶著走**：支援匯出手機行事曆 (.ics)
        """)
        st.info("💡 建議先以「訪客模式」試用，覺得好用再註冊儲存！")

    with login_col:
        with st.container(border=True):
            st.subheader("🔐 用戶登入")
            with st.form("login_form"):
                input_id = st.text_input("👤 暱稱 / 帳號", placeholder="例如: Kevin")
                # 這裡 PIN 碼暫時只做為簡單驗證，若要嚴格安全需搭配資料庫
                input_pin = st.text_input("🔑 密碼 (PIN)", type="password", placeholder="自訂 4-6 碼")
                
                b1, b2 = st.columns(2)
                with b1:
                    submit = st.form_submit_button("🚀 登入 / 註冊", use_container_width=True)
            
            # 訪客按鈕獨立於 Form 之外
            if st.button("👀 免登入試用", use_container_width=True):
                st.session_state.is_guest = True
                st.session_state.user_id = "Guest"
                st.session_state.is_logged_in = True
                st.rerun()

            if submit:
                if input_id and input_pin:
                    with st.spinner("正在讀取雲端行程..."):
                        # 嘗試讀取
                        saved_ids = load_user_saved_ids(input_id)
                        st.session_state.saved_ids = saved_ids
                        st.session_state.user_id = input_id
                        st.session_state.user_pin = input_pin # 暫存 PIN 供未來擴充驗證用
                        st.session_state.is_guest = False
                        st.session_state.is_logged_in = True
                    st.rerun()
                else:
                    st.error("請輸入暱稱與密碼")
    st.stop() 

# ==========================================
# 主程式 (登入後)
# ==========================================

# 側邊欄：顯示用戶狀態
with st.sidebar:
    if st.session_state.is_guest:
        st.warning("👀 目前為訪客模式")
        st.caption("無法使用雲端儲存功能")
    else:
        st.success(f"👤 Hi, {st.session_state.user_id}")
    
    st.markdown("---")
    if st.button("🚪 登出 / 結束試用", use_container_width=True):
        st.session_state.is_logged_in = False
        st.session_state.is_guest = False
        st.session_state.user_id = ""
        st.session_state.saved_ids = []
        st.rerun()

# 讀取 Master 資料
raw_df, msg = load_master_data()

if raw_df is None or raw_df.empty:
    st.error(f"⚠️ 系統維護中 (資料讀取失敗)：{msg}")
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

# 全域變數
all_selected_ids = []
current_selection_counts = {}

# --- 標題區 ---
st.title("📅 2026 書展排程神器")
if st.session_state.is_guest:
    st.caption("目前為試用模式，勾選資料將在關閉視窗後消失。如需長久保存，請登入使用。")

# ==========================================
# 區塊 1：活動清單與勾選 (上方)
# ==========================================
st.subheader("1. 勾選活動 ✅")

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
                    # 隱藏欄位
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

c_cal_head, c_cal_save = st.columns([0.7, 0.3])
with c_cal_head:
    if len(final_selected) > 0:
        st.success(f"已顯示 {len(final_selected)} 場活動")
with c_cal_save:
    # 儲存按鈕邏輯
    if st.session_state.is_guest:
        st.button("💾 儲存 (訪客無法使用)", disabled=True, use_container_width=True)
    else:
        if st.button("💾 儲存到雲端", type="primary", use_container_width=True):
            with st.spinner("正在同步資料至您的雲端檔案..."):
                success, s_msg = save_user_schedule_to_cloud(
                    st.session_state.user_id, 
                    final_selected
                )
                if success:
                    st.toast("✅ 儲存成功！檔案已更新。")
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
            if detail: desc_parts.append(f"\n📝 內容:\n{detail}")
            elif note: desc_parts.append(f"\n📝 備註: {note}")
            
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

# ==========================================
# 隱私權與資料聲明 (Footer)
# ==========================================
st.markdown("<br><br>", unsafe_allow_html=True)
with st.expander("ℹ️ 隱私權與使用聲明 (Privacy Policy)", expanded=False):
    st.markdown("""
    **1. 資料儲存：**
    * 本應用程式僅在您選擇「登入」並按下「儲存」時，才會將您的行程資料儲存至 Google Drive。
    * 每個使用者的資料皆儲存於獨立的檔案中，不會與他人混淆。
    
    **2. 訪客模式：**
    * 訪客模式下，您的所有操作僅保留在當前瀏覽器視窗中，關閉視窗後即自動清除，不會上傳至任何伺服器。
    
    **3. 免責聲明：**
    * 本系統活動資料蒐集自書展官方網站與公開資訊，僅供參考。
    * 活動時間、地點若有變動，請以主辦單位現場公告為準。
    
    **4. 專案資訊：**
    * This app is a personal project designed for the 2026 Taipei International Book Exhibition.
    """)