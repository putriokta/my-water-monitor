from flask import Flask
import pandas as pd
from pmdarima import auto_arima
import requests
import threading
import traceback
import time
import pytz
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)

app = Flask(__name__)

# === KONFIGURASI ===
TOKEN = "7724051850:AAFRc5UYlabkgAwriXHh51OeaNdXlGDRjUk"
CHAT_ID = "1027769170"
CHANNEL_ID = "2761831"
TIMEZONE = pytz.timezone("Asia/Makassar")

# === STATE NOTIFIKASI ===
last_status = ""
last_sent_time = 0

# === AMBIL DATA ===
def ambil_data_thingspeak(jumlah_data=100):
    try:
        timestamp = int(time.time())
        url = f"https://api.thingspeak.com/channels/2761831/feeds.csv?results={jumlah_data}&_={timestamp}"
        df = pd.read_csv(url)
        df.rename(columns={'field1': 'pH', 'field2': 'suhu', 'created_at': 'waktu'}, inplace=True)
        df['waktu'] = pd.to_datetime(df['waktu'], utc=True).dt.tz_convert(TIMEZONE)
        df['pH'] = pd.to_numeric(df['pH'], errors='coerce')
        df['suhu'] = pd.to_numeric(df['suhu'], errors='coerce')
        df = df[['waktu', 'pH', 'suhu']].dropna()
        return df
    except Exception as e:
        print("❌ Gagal ambil data:", e)
        return pd.DataFrame()

# === TELEGRAM ===
def kirim_telegram(pesan):
    try:
        url = f"https://api.telegram.org/bot7724051850:AAFRc5UYlabkgAwriXHh51OeaNdXlGDRjUk/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": pesan}
        response = requests.post(url, data=payload)
        if response.status_code == 200:
            print("📤 Telegram dikirim.")
        else:
            print("⚠️ Gagal kirim:", response.text)
    except Exception as e:
        print("❌ Error kirim Telegram:", e)

# === RULE BASE ===
def cek_rulebase(ph, suhu):
    if ph <= 6.5 or ph >= 8.9 or suhu <= 26 or suhu >= 29:
        return "🚨 Air mendekati ambang batas, harap melakukan pengecekkan kondisi air"
    return "✅ Air dalam kondisi normal"

# === DETEKSI + PREDIKSI + NOTIF ===
def deteksi_dan_prediksi(df):
    global last_status, last_sent_time
    try:
        waktu_terakhir = df['waktu'].iloc[-1]
        data_ph = df['pH'].dropna()
        data_suhu = df['suhu'].dropna()
        aktual_ph = data_ph.iloc[-1]
        aktual_suhu = data_suhu.iloc[-1]

        if len(data_ph) < 30 or len(data_suhu) < 30:
            print("⚠️ Data tidak cukup.")
            return

        model_ph = auto_arima(data_ph, seasonal=False, suppress_warnings=True, stepwise=True)
        model_suhu = auto_arima(data_suhu, seasonal=False, suppress_warnings=True, stepwise=True)

        pred_ph = model_ph.predict(n_periods=5).tolist()
        pred_suhu = model_suhu.predict(n_periods=5).tolist()

        ph_5 = pred_ph[4]
        suhu_5 = pred_suhu[4]
        waktu_pred_5 = waktu_terakhir + pd.Timedelta(minutes=5)

        status = cek_rulebase(ph_5, suhu_5)

        # Kirim jika status berubah ATAU sudah lewat 5 menit
        waktu_sekarang = time.time()
        if status != last_status or waktu_sekarang - last_sent_time >= 300:
            if "🚨" in status:
                pesan = (
                    f"{status}\n"
                    f"📍 Waktu Aktual: {waktu_terakhir.strftime('%H:%M:%S')} WITA\n"
                    f"pH: {aktual_ph:.2f} | Suhu: {aktual_suhu:.2f}°C\n"
                    f"\n🔮 Prediksi 5 Menit ke Depan ({waktu_pred_5.strftime('%H:%M:%S')} WITA):\n"
                    f"pH: {ph_5:.2f} | Suhu: {suhu_5:.2f}°C"
                )
                kirim_telegram(pesan)
                last_status = status
                last_sent_time = waktu_sekarang
            else:
                print("✅ Kondisi normal, tidak kirim pesan.")
        else:
            print("⏳ Menunggu kondisi berubah atau 5 menit berlalu.")
    except Exception:
        traceback.print_exc()

# === LOOP PER MENIT ===
def loop_monitoring():
    df = ambil_data_thingspeak(60)
    if not df.empty:
        deteksi_dan_prediksi(df)
    threading.Timer(60, loop_monitoring).start()

# === WEB UNTUK TAMPILAN MANUAL ===
@app.route('/')
def index():
    try:
        df = ambil_data_thingspeak(60)
        if df.empty:
            return "<p>⚠️ Data kosong.</p>"

        waktu_terakhir = df['waktu'].iloc[-1]
        data_ph = df['pH']
        data_suhu = df['suhu']
        aktual_ph = data_ph.iloc[-1]
        aktual_suhu = data_suhu.iloc[-1]

        model_ph = auto_arima(data_ph, seasonal=False, suppress_warnings=True, stepwise=True)
        model_suhu = auto_arima(data_suhu, seasonal=False, suppress_warnings=True, stepwise=True)

        pred_ph = model_ph.predict(n_periods=5).tolist()
        pred_suhu = model_suhu.predict(n_periods=5).tolist()

        ph_1 = pred_ph[0]
        suhu_1 = pred_suhu[0]
        ph_5 = pred_ph[4]
        suhu_5 = pred_suhu[4]
        waktu_pred_1 = waktu_terakhir + pd.Timedelta(minutes=1)
        waktu_pred_5 = waktu_terakhir + pd.Timedelta(minutes=5)

        status = cek_rulebase(ph_5, suhu_5)

        return f"""
        <h2>📊 Monitoring Kualitas Air</h2>
        <ul>
            <li>🕒 Waktu Aktual: <b>{waktu_terakhir.strftime('%Y-%m-%d %H:%M:%S')} (WITA)</b></li>
            <li>📌 Aktual → pH: <b>{aktual_ph:.2f}</b> | Suhu: <b>{aktual_suhu:.2f}°C</b></li>
            <li>🔮 Prediksi 1 Menit → pH: <b>{ph_1:.2f}</b> | Suhu: <b>{suhu_1:.2f}°C</b> @ {waktu_pred_1.strftime('%H:%M:%S')}</li>
            <li>🔮 Prediksi 5 Menit → pH: <b>{ph_5:.2f}</b> | Suhu: <b>{suhu_5:.2f}°C</b> @ {waktu_pred_5.strftime('%H:%M:%S')}</li>
            <li>📋 Status Prediksi: <b>{status}</b></li>
        </ul>
        """
    except Exception:
        traceback.print_exc()
        return "<p>❌ Terjadi error saat prediksi.</p>"

# === JALANKAN ===
if __name__ == '__main__':
    threading.Thread(target=loop_monitoring).start()
    app.run(debug=False, use_reloader=False)

