import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import requests
import datetime
import time
import re
import urllib3

# 1. 頁面設定
st.set_page_config(page_title="2026 書展採購清單", page_icon="📚", layout="wide")

# 設定區
SHEET_NAME = "2026國際書展採購清單"
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 2. 連線功能 (無快取，確保穩定) ---
def connect_to_spreadsheet():
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
        spreadsheet = client.open(SHEET_NAME)
        return spreadsheet
    except Exception as e:
        return None

# --- 3. 取得分頁 (核心穩定邏輯) ---
def get_or_create_sheet(spreadsheet, user_id):
    safe_id = re.sub(r'[^a-zA-Z0-9_\u4e00-\u9fa5]', '', str(user_id))
    if not safe_id: return None
    
    try:
        sheet = spreadsheet.worksheet(safe_id)
        return sheet
    except gspread.WorksheetNotFound:
        # 🔥 關鍵：建立時只給 1 行標題，避免幽靈空行
        try:
            sheet = spreadsheet.add_worksheet(title=safe_id, rows=1, cols=10)
            sheet.update(range_name='A1', values=[["建檔時間", "書名", "作者", "ISBN", "價格", "狀態"]])
            return sheet
        except Exception as e:
            st.error(f"建立分頁失敗: {e}")
            return None

# --- 4. 爬蟲工具 ---
def clean_isbn_func(isbn_raw):
    return str(isbn_raw).strip().replace("-", "").replace(" ", "").replace("\n", "").replace("\t", "") if isbn_raw else ""

def search_google_books(isbn):
    clean_isbn = clean_isbn_func(isbn)
    url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{clean_isbn}"
    try:
        res = requests.get(url, timeout=3).json()
        if "items" in res:
            info = res["items"][0]["volumeInfo"]
            return {
                "書名": info.get("title", ""),
                "作者": ", ".join(info.get("authors", [])),
                "封面": info.get("imageLinks", {}).get("thumbnail", ""),
                "found": True
            }
    except: pass
    return {"found": False}

def smart_book_search(isbn_input):
    if not isbn_input: return None
    clean_isbn = clean_isbn_func(isbn_input)
    result = {"書名": "", "作者": "", "ISBN": clean_isbn, "封面": "", "定價": "", "建檔時間": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "found": False}
    g_data = search_google_books(clean_isbn)
    if g_data["found"]:
        result.update(g_data)
        result["found"] = True
    return result

# --- 5. 資料儲存 (用於編輯模式) ---
def save_data_overwrite(sheet, df):
    try:
        # 轉成 List
        data = [df.columns.values.tolist()] + df.values.tolist()
        # 清空並重寫 (這是編輯功能必需的)
        sheet.clear()
        sheet.update(range_name='A1', values=data)
        return True
    except Exception as e:
        st.error(f"儲存失敗: {e}")
        return False

# --- 主程式介面 ---

# 側邊欄：登入
st.sidebar.title("🔐 登入")
if "user_id" not in st.session_state: st.session_state.user_id = ""
if "budget" not in st.session_state: st.session_state.budget = 3000

input_id = st.sidebar.text_input("輸入暱稱 (ID)", value=st.session_state.user_id)
if input_id:
    st.session_state.user_id = input_id
    st.sidebar.success(f"Hi, {input_id}")
    st.session_state.budget = st.sidebar.number_input("💰 總預算", value=st.session_state.budget, step=500)
else:
    st.title("📚 2026 書展採購清單")
    st.info("👈 請先在左側輸入暱稱以開始使用")
    st.stop()

# 連線與讀取
ss = connect_to_spreadsheet()
if not ss: st.stop()
sheet = get_or_create_sheet(ss, input_id)
if not sheet: st.stop()

# 標題區
st.title(f"🛒 {input_id} 的書展清單")

# --- 讀取資料並整理 ---
try:
    data = sheet.get_all_values()
    if len(data) > 0:
        df = pd.DataFrame(data[1:], columns=data[0])
    else:
        # 萬一真的全是空的，重建標題
        df = pd.DataFrame(columns=["建檔時間", "書名", "作者", "ISBN", "價格", "狀態"])
except:
    df = pd.DataFrame(columns=["建檔時間", "書名", "作者", "ISBN", "價格", "狀態"])

# 預算計算
df['價格'] = pd.to_numeric(df['價格'], errors='coerce').fillna(0)
total = df[df['狀態'].isin(['待購', '已購'])]['價格'].sum()
remain = st.session_state.budget - total

# 儀表板
col1, col2, col3 = st.columns(3)
col1.metric("📚 書籍數", f"{len(df)} 本")
col2.metric("💸 預計花費", f"${int(total)}")
col3.metric("💰 剩餘預算", f"${int(remain)}", delta_color="normal" if remain >= 0 else "inverse")

if remain < 0:
    st.error(f"⚠️ 預算超支 ${abs(int(remain))} 元！")

st.divider()

# --- A 區：新增書籍 ---
with st.expander("🔍 **新增書籍 (掃描/搜尋)**", expanded=True):
    c1, c2 = st.columns([1, 2])
    with c1:
        isbn_in = st.text_input("輸入 ISBN")
        if st.button("🔍 找書"):
            if isbn_in:
                res = smart_book_search(isbn_in)
                st.session_state.search_res = res

    if 'search_res' in st.session_state and st.session_state.search_res:
        res = st.session_state.search_res
        if res['found']: st.success(f"✅ 找到：{res['書名']}")
        else: st.warning("⚠️ 未找到資料，請手動填寫")

        with st.form("add_form"):
            cc1, cc2 = st.columns([1, 2])
            with cc1:
                if res['封面']: st.image(res['封面'], width=100)
                
                # 查價連結
                clean_isbn = clean_isbn_func(res['ISBN'])
                st.markdown(f'''
                <a href="https://search.books.com.tw/search/query/key/{clean_isbn}" target="_blank">🔍 博客來</a>｜
                <a href="https://findbook.tw/book/{clean_isbn}/price" target="_blank">🔍 Findbook</a>
                ''', unsafe_allow_html=True)

            with cc2:
                n_title = st.text_input("書名", value=res['書名'])
                n_author = st.text_input("作者", value=res['作者'])
                n_price = st.text_input("價格", value=res['定價'])
                
                if st.form_submit_button("➕ 加入清單"):
                    new_row = [res['建檔時間'], n_title, n_author, res['ISBN'], n_price, "待購"]
                    try:
                        sheet.append_row(new_row) # 使用最穩的 append_row
                        st.toast(f"已加入：{n_title}")
                        time.sleep(0.5)
                        del st.session_state.search_res
                        st.rerun()
                    except Exception as e:
                        st.error(f"寫入失敗: {e}")

st.divider()

# --- B 區：清單管理 (編輯 & 封面牆) ---
tab1, tab2 = st.tabs(["📝 編輯清單", "🖼️ 封面牆"])

with tab1:
    if df.empty:
        st.info("目前沒有書籍。")
    else:
        # 使用 data_editor 讓使用者可以修改
        edited_df = st.data_editor(
            df,
            use_container_width=True,
            num_rows="dynamic",
            key="editor",
            column_config={
                "價格": st.column_config.NumberColumn("價格", format="$%d"),
                "狀態": st.column_config.SelectboxColumn("狀態", options=["待購", "已購", "猶豫中", "放棄"])
            }
        )
        
        col_save, _ = st.columns([1, 4])
        with col_save:
            if st.button("💾 儲存修改", type="primary"):
                with st.spinner("同步回雲端中..."):
                    if save_data_overwrite(sheet, edited_df):
                        st.success("✅ 儲存成功！")
                        time.sleep(1)
                        st.rerun()

with tab2:
    if not df.empty:
        cols = st.columns(4)
        for idx, row in df.iterrows():
            with cols[idx % 4]:
                # 簡單顯示封面
                if row['ISBN']:
                    img = search_google_books(row['ISBN'])['封面']
                    if img: st.image(img, use_container_width=True)
                    else: st.markdown("📚")
                st.caption(f"**{row['書名']}**")
                st.caption(f"${row['價格']} | {row['狀態']}")
                st.markdown("---")
    else:
        st.info("尚無書籍可展示")