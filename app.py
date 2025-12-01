import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
import random
from datetime import datetime, timedelta
from fpdf import FPDF
import base64
import os
import cloudinary
import cloudinary.uploader
import cloudinary.api

# --- CONFIGURACIÓN GENERAL ---
st.set_page_config(page_title="Sistema Pandero", page_icon="💰", layout="wide")

# --- ESTILOS CSS ---
st.markdown("""
    <style>
    .group-card { background-color: #262730; border: 1px solid #4F4F4F; border-radius: 10px; padding: 20px; margin-bottom: 20px; }
    .highlight-green { color: #00cc66; font-weight: bold; }
    .user-week-card { background-color: #1E1E1E; padding: 12px; margin-bottom: 8px; border-radius: 6px; display: flex; justify_content: space-between; border-left: 5px solid #555; }
    .half-turn-tag { background-color: #3498db; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px; margin-left: 5px; }
    [data-testid="stDataFrame"] th { text-align: center !important; }
    [data-testid="stDataFrame"] td { text-align: center !important; }
    .big-btn { width: 100%; padding: 10px; }
    </style>
    """, unsafe_allow_html=True)

# --- CONEXIÓN CLOUDINARY ---
def init_cloudinary():
    try:
        cloudinary.config(
            cloud_name = st.secrets["cloudinary"]["cloud_name"],
            api_key = st.secrets["cloudinary"]["api_key"],
            api_secret = st.secrets["cloudinary"]["api_secret"],
            secure = True
        )
    except: pass
init_cloudinary()

# --- CONEXIÓN GOOGLE SHEETS ---
def conectar_db(hoja_nombre):
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sh = client.open("BASE_DATOS_PANDERO") 
        return sh.worksheet(hoja_nombre)
    except Exception as e:
        st.error(f"⚠️ Error de conexión (Espera 1 min): {e}")
        st.stop()

# --- FUNCION DE CARGA CON CACHÉ (SOLUCIÓN ERROR 429) ---
# ttl=60: Mantiene los datos en memoria 60 segundos antes de volver a llamar a Google
@st.cache_data(ttl=60, show_spinner=False)
def cargar_df(hoja, columnas_obligatorias):
    # Usamos try/except para manejar errores de conexión silenciosamente
    try:
        ws = conectar_db(hoja)
        data = ws.get_all_records()
    except:
        return pd.DataFrame(columns=columnas_obligatorias)

    if not data:
        try: 
            headers = ws.row_values(1)
            if not headers: ws.append_row(columnas_obligatorias)
        except: pass
        return pd.DataFrame(columns=columnas_obligatorias)
    
    df = pd.DataFrame(data).astype(str)
    for col in columnas_obligatorias:
        if col not in df.columns: df[col] = "" 
    return df

def guardar_df_completo(hoja, df):
    try:
        ws = conectar_db(hoja)
        ws.clear()
        ws.update([df.columns.values.tolist()] + df.values.tolist())
        # IMPORTANTE: Limpiamos la caché para que se vean los cambios
        st.cache_data.clear()
    except Exception as e:
        st.error(f"No se pudo guardar: {e}")

# --- VARIABLES ---
TAB_USUARIOS = 'usuarios'; COLS_USUARIOS = ["Nombre", "DNI", "Celular"]
TAB_GRUPOS = 'grupos'; COLS_GRUPOS = ["NombreGrupo", "FechaInicio", "SemanasDuracion", "MontoBase", "MontoInteres"]
TAB_MIEMBROS = 'miembros'; COLS_MIEMBROS = ["NombreGrupo", "DNI_Usuario", "Turno", "Tipo"]
TAB_PAGOS = 'pagos'; COLS_PAGOS = ["Fecha", "DNI", "Grupo", "Monto", "Estado", "Foto", "SemanaPagada"]

def limpiar_fecha(fecha_str): return str(fecha_str).split(" ")[0]

# --- PDF ---
def crear_reporte_pdf(nombre_grupo, datos_miembros):
    class PDF(FPDF):
        def header(self):
            self.set_font('Arial', 'B', 15); self.cell(0, 10, f'Reporte: {nombre_grupo}', 0, 1, 'C'); self.ln(5)
    pdf = PDF(); pdf.add_page(); pdf.set_font("Arial", size=10); pdf.set_fill_color(200, 220, 255)
    pdf.cell(80, 10, "Socio", 1, 0, 'C', 1); pdf.cell(20, 10, "Turno", 1, 0, 'C', 1)
    pdf.cell(30, 10, "Pagado", 1, 0, 'C', 1); pdf.cell(30, 10, "Deuda", 1, 0, 'C', 1); pdf.cell(30, 10, "Estado", 1, 1, 'C', 1)
    for m in datos_miembros:
        pdf.cell(80, 10, str(m['Nombre']), 1); pdf.cell(20, 10, str(m['Turno']), 1, 0, 'C')
        pdf.cell(30, 10, f"S/. {m['Pagado']}", 1, 0, 'R'); pdf.cell(30, 10, str(m['Deuda']), 1, 0, 'C')
        pdf.set_text_color(255, 0, 0) if m['Deuda'] > 0 else pdf.set_text_color(0, 128, 0)
        pdf.cell(30, 10, "DEUDA" if m['Deuda'] > 0 else "OK", 1, 1, 'C'); pdf.set_text_color(0)
    return pdf.output(dest='S').encode('latin-1')

# --- CÁLCULOS ---
def generar_calendario_usuario(dni_usuario):
    df_m = cargar_df(TAB_MIEMBROS, COLS_MIEMBROS); df_g = cargar_df(TAB_GRUPOS, COLS_GRUPOS); df_p = cargar_df(TAB_PAGOS, COLS_PAGOS)
    if df_m.empty: return [], "Sin Grupo", "Completo"
    df_m['DNI_Usuario'] = df_m['DNI_Usuario'].astype(str); dni_usuario = str(dni_usuario)
    fila = df_m[df_m['DNI_Usuario'] == dni_usuario]
    if fila.empty: return [], "Sin Grupo", "Completo"
    
    dat_m = fila.iloc[0]; grupo = dat_m['NombreGrupo']
    try: turno = int(float(dat_m.get('Turno', 0)))
    except: turno = 0
    tipo_p = dat_m.get('Tipo', 'Completo'); factor = 0.5 if tipo_p == 'Medio' else 1.0
    
    # Check si grupo existe
    g_idx = df_g[df_g['NombreGrupo'] == grupo]
    if g_idx.empty: return [], "Grupo Eliminado", "Completo"
    
    dat_g = g_idx.iloc[0]
    inicio = datetime.strptime(limpiar_fecha(dat_g['FechaInicio']), "%Y-%m-%d")
    duracion = int(float(dat_g['SemanasDuracion']))
    base = float(dat_g.get('MontoBase', 400)) * factor; interes = float(dat_g.get('MontoInteres', 430)) * factor
    
    mis_pagos = df_p[(df_p['DNI'] == dni_usuario) & (df_p['Grupo'] == grupo)] if not df_p.empty else pd.DataFrame()
    tot_pagado = 0; tot_pendiente = 0
    if not mis_pagos.empty:
        try: tot_pagado = mis_pagos[mis_pagos['Estado'] == 'Aprobado']['Monto'].astype(float).sum()
        except: pass
        try: tot_pendiente = mis_pagos[mis_pagos['Estado'] == 'Pendiente']['Monto'].astype(float).sum()
        except: pass
        
    cal = []; hoy = datetime.now(); acumulado = 0
    for i in range(duracion):
        num = i + 1; fecha = inicio + timedelta(weeks=i)
        monto = interes if (turno > 0 and num > turno) else base
        acumulado += monto
        estado = "grey"
        if tot_pagado >= acumulado: estado = "green"
        elif (tot_pagado + tot_pendiente) >= acumulado: estado = "orange"
        elif tot_pagado >= (acumulado - monto) and tot_pagado < acumulado: estado = "yellow"
        elif fecha < hoy: estado = "red"
        cal.append({"Semana": num, "Fecha": fecha.strftime("%d/%m"), "Monto": monto, "Estado": estado})
    return cal, grupo, tipo_p

# --- ESTADOS ---
if 'usuario' not in st.session_state: st.session_state.usuario = None
if 'login_step' not in st.session_state: st.session_state.login_step = 'dni'

with st.sidebar:
    st.title("🏛️ PANDERO")
    if st.session_state.usuario:
        st.success(f"Hola, {st.session_state.nombre_pila}")
        if st.button("Cerrar Sesión"):
            st.session_state.usuario = None; st.session_state.login_step = 'dni'; st.rerun()

# 1. LOGIN
if st.session_state.usuario is None:
    c_izq, c_centro, c_der = st.columns([1, 2, 1])
    with c_centro:
        st.markdown("<h2 style='text-align: center;'>Bienvenido</h2>", unsafe_allow_html=True); st.markdown("---")
        if st.session_state.login_step == 'registro':
            st.subheader("📝 Registro")
            with st.form("form_registro"):
                new_nombre = st.text_input("Nombre Completo"); new_dni = st.text_input("DNI (Usuario)"); new_cel = st.text_input("Celular")
                if st.form_submit_button("Registrarme Ahora", type="primary", use_container_width=True):
                    if new_nombre and new_dni:
                        df_u = cargar_df(TAB_USUARIOS, COLS_USUARIOS)
                        if new_dni in df_u['DNI'].values: st.error("DNI ya registrado.")
                        else:
                            nuevo = pd.DataFrame([{"Nombre": new_nombre, "DNI": new_dni, "Celular": new_cel}])
                            guardar_df_completo(TAB_USUARIOS, pd.concat([df_u, nuevo], ignore_index=True))
                            st.success("¡Cuenta creada!"); time.sleep(2); st.session_state.login_step = 'dni'; st.rerun()
                    else: st.warning("Faltan datos")
            if st.button("⬅️ Volver"): st.session_state.login_step = 'dni'; st.rerun()
        elif st.session_state.login_step == 'password':
            st.info("🔒 Admin")
            pass_input = st.text_input("Contraseña", type="password")
            c_a, c_b = st.columns(2)
            if c_a.button("Acceder", type="primary", use_container_width=True):
                if pass_input == "admin123":
                    st.session_state.usuario = "ADMIN"; st.session_state.rol = 'admin'; st.session_state.nombre_pila = "Admin"; st.rerun()
                else: st.error("Incorrecto")
            if c_b.button("Cancelar", use_container_width=True): st.session_state.login_step = 'dni'; st.rerun()
        else: 
            dni_input = st.text_input("Ingresa tu DNI")
            if st.button("Continuar", type="primary", use_container_width=True):
                if dni_input.strip().upper() == "ADMIN": st.session_state.login_step = 'password'; st.rerun()
                else:
                    df_u = cargar_df(TAB_USUARIOS, COLS_USUARIOS)
                    if not df_u.empty and str(dni_input) in df_u['DNI'].values:
                        st.session_state.usuario = str(dni_input); st.session_state.rol = 'usuario'
                        st.session_state.nombre_pila = df_u[df_u['DNI']==str(dni_input)].iloc[0]['Nombre']; st.rerun()
                    else: st.error("DNI no encontrado.")
            st.markdown(" "); st.markdown("<p style='text-align: center;'>¿Nuevo?</p>", unsafe_allow_html=True)
            if st.button("Crear Cuenta", use_container_width=True): st.session_state.login_step = 'registro'; st.rerun()

# 2. ADMIN
elif st.session_state.rol == 'admin':
    if 'grupo_sel' not in st.session_state: st.session_state.grupo_sel = None
    if not st.session_state.grupo_sel:
        st.header("Panel de Control")
        with st.expander("➕ Crear Nuevo Grupo"):
            c1, c2 = st.columns(2)
            n_nuevo = c1.text_input("Nombre Grupo"); f_nuevo = c2.date_input("Fecha Inicio")
            c3, c4, c5 = st.columns(3)
            d = c3.number_input("Semanas", 1, 50, 25); mb = c4.number_input("Base", 400.0); mi = c5.number_input("Interés", 430.0)
            if st.button("Crear"):
                df_g = cargar_df(TAB_GRUPOS, COLS_GRUPOS)
                if not df_g.empty and n_nuevo in df_g['NombreGrupo'].values: st.error("Existe")
                else:
                    new = pd.DataFrame([{"NombreGrupo":n_nuevo, "FechaInicio":str(f_nuevo), "SemanasDuracion":d, "MontoBase":mb, "MontoInteres":mi}])
                    guardar_df_completo(TAB_GRUPOS, pd.concat([df_g, new], ignore_index=True)); st.success("Hecho"); st.rerun()
        df_g = cargar_df(TAB_GRUPOS, COLS_GRUPOS)
        if not df_g.empty:
            cols = st.columns(3)
            for i, r in df_g.iterrows():
                with cols[i%3]:
                    st.info(f"📁 {r['NombreGrupo']}")
                    if st.button(f"Entrar {r['NombreGrupo']}"): st.session_state.grupo_sel = r['NombreGrupo']; st.rerun()
        else: st.info("No hay grupos.")
    else:
        grupo = st.session_state.grupo_sel
        if st.button("⬅️ Volver"): st.session_state.grupo_sel = None; st.rerun()
        st.title(f"Gestión: {grupo}")
        t1, t2, t3, t4, t5, t6 = st.tabs(["Miembros", "Inscribir", "Sorteo", "Ajustes", "Pagos", "Reportes"])
        with t1:
            df_m = cargar_df(TAB_MIEMBROS, COLS_MIEMBROS); df_u = cargar_df(TAB_USUARIOS, COLS_USUARIOS)
            mis_m = df_m[df_m['NombreGrupo']==grupo]
            if not mis_m.empty:
                mis_m['TurnoNum'] = pd.to_numeric(mis_m['Turno'], errors='coerce').fillna(0)
                mis_m = mis_m.sort_values(by='TurnoNum')
                dat = pd.merge(mis_m, df_u, left_on="DNI_Usuario", right_on="DNI")
                for _, r in dat.iterrows():
                    cal, _, _ = generar_calendario_usuario(r['DNI'])
                    deuda = sum(1 for c in cal if c['Estado']=='red')
                    tag = '½' if r['Tipo']=='Medio' else ''
                    with st.expander(f"T{r['Turno']} | {'🔴' if deuda>0 else '🟢'} {r['Nombre']} {tag}"):
                        c1, c2 = st.columns([3,1])
                        c1.write(f"DNI: {r['DNI']} | Deuda: {deuda}"); c1.markdown(f"[📲 WhatsApp](https://wa.me/?text=Hola%20{r['Nombre']})")
                        c2.metric("Pagado", f"S/. {sum(c['Monto'] for c in cal if c['Estado']=='green')}")
                        dfv = pd.DataFrame(cal)[['Semana','Fecha','Monto','Estado']]
                        dfv['Monto'] = dfv['Monto'].apply(lambda x: f"S/. {x:.2f}")
                        dfv['Estado'] = dfv['Estado'].map({'red':'🔴','green':'🟢','grey':'⚪','orange':'🟠','yellow':'🟡'})
                        st.dataframe(dfv, hide_index=True, use_container_width=True)
            else: st.info("Sin miembros")
        with t2:
            st.write("Inscribir Socio")
            busq = st.text_input("Buscar DNI/Nombre")
            df_u = cargar_df(TAB_USUARIOS, COLS_USUARIOS)
            if not df_u.empty:
                filtro = df_u[df_u['Nombre'].str.contains(busq, case=False)|df_u['DNI'].astype(str).str.contains(busq)] if busq else df_u
                sel = st.selectbox("Seleccionar", filtro['DNI'] + " - " + filtro['Nombre'])
                c1, c2 = st.columns(2)
                df_g_curr = cargar_df(TAB_GRUPOS, COLS_GRUPOS)
                dur = int(float(df_g_curr[df_g_curr['NombreGrupo']==grupo].iloc[0]['SemanasDuracion']))
                turn = c1.number_input("Turno", 1, dur); medio = c2.checkbox("Medio Turno")
                if st.button("Inscribir"):
                    dni = sel.split(" - ")[0]
                    df_mm = cargar_df(TAB_MIEMBROS, COLS_MIEMBROS)
                    if df_mm[(df_mm['NombreGrupo']==grupo)&(df_mm['DNI_Usuario']==dni)].empty:
                        new = pd.DataFrame([{"NombreGrupo":grupo, "DNI_Usuario":dni, "Turno":turn, "Tipo":'Medio' if medio else 'Completo'}])
                        guardar_df_completo(TAB_MIEMBROS, pd.concat([df_mm, new], ignore_index=True))
                        st.success("Inscrito"); st.rerun()
                    else: st.error("Ya está")
        with t3:
            if st.button("🎲 Sortear Turnos"):
                df_mm = cargar_df(TAB_MIEMBROS, COLS_MIEMBROS)
                idxs = df_mm.index[df_mm['NombreGrupo']==grupo].tolist()
                if idxs:
                    ts = list(range(1, len(idxs)+1)); random.shuffle(ts)
                    for i, x in enumerate(idxs): df_mm.at[x, 'Turno'] = ts[i]
                    guardar_df_completo(TAB_MIEMBROS, df_mm); st.success("Listo!"); st.balloons()
        with t4: st.info("Edita en Google Sheets")
        with t5:
            st.subheader("Validación")
            t_rev, t_man = st.tabs(["Con Foto", "Manual"])
            df_p = cargar_df(TAB_PAGOS, COLS_PAGOS); df_u = cargar_df(TAB_USUARIOS, COLS_USUARIOS)
            with t_rev:
                pend = df_p[(df_p['Grupo']==grupo)&(df_p['Estado']=='Pendiente')]
                if not pend.empty:
                    view = pd.merge(pend, df_u, on="DNI")
                    for idx, r in view.iterrows():
                        with st.container(border=True):
                            c1, c2 = st.columns(2)
                            c1.write(f"**{r['Nombre']}** | {r.get('SemanaPagada')}")
                            c1.write(f"Monto: S/. {r['Monto']}")
                            if str(r['Foto']).startswith('http'): c1.image(r['Foto'], use_container_width=True)
                            else: c1.warning("Foto local")
                            if c2.button("✅", key=f"y{idx}"):
                                mask = (df_p['DNI']==r['DNI'])&(df_p['Fecha']==r['Fecha'])&(df_p['Monto']==r['Monto'])
                                df_p.at[df_p[mask].index[0], 'Estado']='Aprobado'
                                guardar_df_completo(TAB_PAGOS, df_p); st.rerun()
                            if c2.button("❌", key=f"n{idx}"):
                                mask = (df_p['DNI']==r['DNI'])&(df_p['Fecha']==r['Fecha'])&(df_p['Monto']==r['Monto'])
                                df_p.at[df_p[mask].index[0], 'Estado']='Rechazado'
                                guardar_df_completo(TAB_PAGOS, df_p); st.rerun()
                else: st.info("Nada pendiente")
            with t_man:
                sel_m = st.selectbox("Socio Manual", df_u['DNI']+"-"+df_u['Nombre'])
                if sel_m:
                    dni_m = sel_m.split("-")[0]; cal_m, _, _ = generar_calendario_usuario(dni_m)
                    ops_m = [f"Semana {s['Semana']}" for s in cal_m if s['Estado']!='green']
                    if ops_m:
                        sem_m = st.selectbox("Semana Manual", ops_m); mon_m = st.number_input("Monto Efec.", 0.0)
                        if st.button("Registrar Efectivo"):
                            new = pd.DataFrame([{"Fecha":datetime.now().strftime("%Y-%m-%d"), "DNI":dni_m, "Grupo":grupo, "Monto":str(mon_m), "Estado":"Aprobado", "Foto":"Manual", "SemanaPagada":sem_m}])
                            guardar_df_completo(TAB_PAGOS, pd.concat([df_p, new], ignore_index=True)); st.success("Registrado"); st.rerun()
                    else: st.success("Ya pagó todo.")
        with t6:
            if st.button("PDF"):
                df_mm = cargar_df(TAB_MIEMBROS, COLS_MIEMBROS); df_u = cargar_df(TAB_USUARIOS, COLS_USUARIOS)
                mism = df_mm[df_mm['NombreGrupo']==grupo]
                dat = pd.merge(mism, df_u, left_on="DNI_Usuario", right_on="DNI")
                rep = []
                for _, r in dat.iterrows():
                    cal, _, _ = generar_calendario_usuario(r['DNI'])
                    deuda = sum(1 for c in cal if c['Estado']=='red')
                    pag = sum(c['Monto'] for c in cal if c['Estado']=='green')
                    rep.append({"Nombre":r['Nombre'], "Turno":r['Turno'], "Pagado":pag, "Deuda":deuda})
                pdf_b = crear_reporte_pdf(grupo, rep)
                b64 = base64.b64encode(pdf_b).decode()
                st.markdown(f'<a href="data:application/octet-stream;base64,{b64}" download="Rep.pdf">Descargar</a>', unsafe_allow_html=True)

# 3. USUARIO
elif st.session_state.rol == 'usuario':
    st.title(f"Hola, {st.session_state.nombre_pila}")
    cal, nom_g, tipo_p = generar_calendario_usuario(st.session_state.usuario)
    if cal:
        st.info(f"Grupo: {nom_g} ({tipo_p})")
        df_p = cargar_df(TAB_PAGOS, COLS_PAGOS)
        rech = df_p[(df_p['DNI']==st.session_state.usuario)&(df_p['Estado']=='Rechazado')]
        if not rech.empty: st.error(f"⚠️ Tienes {len(rech)} pago(s) RECHAZADO(S).")
        dfv = pd.DataFrame(cal)[['Semana','Fecha','Monto','Estado']]
        dfv['Monto'] = dfv['Monto'].apply(lambda x: f"S/. {x:.2f}")
        dfv['Estado'] = dfv['Estado'].map({'red':'🔴','green':'🟢','grey':'⚪','orange':'🟠','yellow':'🟡'})
        st.dataframe(dfv, hide_index=True, use_container_width=True)
        with st.form("pay", clear_on_submit=True):
            ops = [f"Semana {s['Semana']} ({s['Fecha']})" for s in cal if s['Estado']!='green']
            if ops:
                sem = st.selectbox("Semana", ops); monto = st.number_input("Monto (S/.)", 0.0)
                uploaded = st.file_uploader("Voucher")
                if st.form_submit_button("Enviar Pago"):
                    if uploaded and monto > 0:
                        try:
                            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                            nombre_archivo = f"S{sem.split()[1]}_{timestamp}"
                            folder_path = f"PANDEROS/{st.session_state.usuario}/{nom_g}"
                            upload_result = cloudinary.uploader.upload(uploaded, folder=folder_path, public_id=nombre_archivo)
                            link_foto = upload_result['secure_url']
                            new = pd.DataFrame([{"Fecha":datetime.now().strftime("%Y-%m-%d"), "DNI":st.session_state.usuario, "Grupo":nom_g, "Monto":str(monto), "Estado":"Pendiente", "Foto":link_foto, "SemanaPagada":sem}])
                            guardar_df_completo(TAB_PAGOS, pd.concat([df_p, new], ignore_index=True))
                            st.success("Enviado ✅"); time.sleep(2); st.rerun()
                        except Exception as e: st.error(f"Error imagen: {e}")
                    else: st.error("Completa todo")
            else: st.success("¡Felicidades! Pagaste todo.")
    else: st.warning("Sin grupo")