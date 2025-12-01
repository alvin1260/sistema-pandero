import streamlit as st
import pandas as pd
import os
import time
import random
from datetime import datetime, timedelta
from fpdf import FPDF
import base64

# --- CONFIGURACIÓN GENERAL ---
st.set_page_config(
    page_title="Sistema Pandero",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- ESTILOS CSS ---
st.markdown("""
    <style>
    /* Estilos Tarjetas Admin */
    .group-card { background-color: #262730; border: 1px solid #4F4F4F; border-radius: 10px; padding: 20px; margin-bottom: 20px; transition: transform 0.2s; }
    .group-card:hover { border-color: #FF4B4B; transform: scale(1.01); }
    .card-header { font-size: 20px; font-weight: bold; color: #FFFFFF; margin-bottom: 10px; border-bottom: 1px solid #444; padding-bottom: 5px; }
    .card-stat { font-size: 14px; color: #B0B0B0; margin: 3px 0; display: flex; justify_content: space-between; }
    .highlight-green { color: #00cc66; font-weight: bold; }
    
    /* Estilos Tarjetas Usuario */
    .user-week-card { background-color: #1E1E1E; padding: 12px; margin-bottom: 8px; border-radius: 6px; display: flex; justify_content: space-between; align-items: center; border-left: 5px solid #555; }
    .half-turn-tag { background-color: #3498db; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px; margin-left: 5px; }
    
    /* Centrar Tablas */
    [data-testid="stDataFrame"] th { text-align: center !important; }
    [data-testid="stDataFrame"] td { text-align: center !important; }
    </style>
    """, unsafe_allow_html=True)

# --- ARCHIVOS ---
FILE_USUARIOS = 'bd_usuarios.xlsx'
FILE_GRUPOS = 'bd_grupos.xlsx'
FILE_MIEMBROS = 'bd_miembros_grupo.xlsx'
FILE_PAGOS = 'bd_pagos.xlsx'
CARPETA_FOTOS = 'fotos_comprobantes'

if not os.path.exists(CARPETA_FOTOS): os.makedirs(CARPETA_FOTOS)

# --- FUNCIONES ---

def cargar_excel(archivo, columnas_defaults):
    columnas_lista = list(columnas_defaults.keys())
    if os.path.exists(archivo):
        df = pd.read_excel(archivo, dtype=str)
        guardar = False
        for col, val_def in columnas_defaults.items():
            if col not in df.columns:
                df[col] = str(val_def)
                guardar = True
        if guardar:
            df.to_excel(archivo, index=False)
        return df
    return pd.DataFrame(columns=columnas_lista)

def guardar_excel(df, archivo):
    df.to_excel(archivo, index=False)

def limpiar_fecha(fecha_str):
    return str(fecha_str).split(" ")[0]

# --- GENERADOR DE PDF ---
def crear_reporte_pdf(nombre_grupo, datos_miembros):
    class PDF(FPDF):
        def header(self):
            self.set_font('Arial', 'B', 15)
            self.cell(0, 10, f'Reporte de Estado: {nombre_grupo}', 0, 1, 'C')
            self.set_font('Arial', 'I', 10)
            self.cell(0, 10, f'Generado: {datetime.now().strftime("%d/%m/%Y %H:%M")}', 0, 1, 'C')
            self.ln(5)

    pdf = PDF()
    pdf.add_page()
    pdf.set_font("Arial", size=10)
    
    pdf.set_fill_color(200, 220, 255)
    pdf.cell(80, 10, "Socio", 1, 0, 'C', 1)
    pdf.cell(20, 10, "Turno", 1, 0, 'C', 1)
    pdf.cell(30, 10, "Pagado", 1, 0, 'C', 1)
    pdf.cell(30, 10, "Deuda", 1, 0, 'C', 1)
    pdf.cell(30, 10, "Estado", 1, 1, 'C', 1)
    
    for m in datos_miembros:
        pdf.cell(80, 10, str(m['Nombre']), 1)
        pdf.cell(20, 10, str(m['Turno']), 1, 0, 'C')
        pdf.cell(30, 10, f"S/. {m['Pagado']}", 1, 0, 'R')
        pdf.cell(30, 10, str(m['Deuda']), 1, 0, 'C')
        estado_txt = "Al Dia" if m['Deuda'] == 0 else "DEUDA"
        if m['Deuda'] > 0: pdf.set_text_color(255, 0, 0)
        else: pdf.set_text_color(0, 128, 0)
        pdf.cell(30, 10, estado_txt, 1, 1, 'C')
        pdf.set_text_color(0, 0, 0)

    return pdf.output(dest='S').encode('latin-1')

# --- LÓGICA DE NEGOCIO ---

def calcular_detalle_grupo(nombre_grupo):
    df_g = cargar_excel(FILE_GRUPOS, {"NombreGrupo":"", "FechaInicio":"", "SemanasDuracion":"25", "MontoBase":"400", "MontoInteres":"430"})
    grupo_subset = df_g[df_g['NombreGrupo'] == nombre_grupo]
    if grupo_subset.empty: return None

    grupo_data = grupo_subset.iloc[0]
    try: inicio = datetime.strptime(limpiar_fecha(grupo_data['FechaInicio']), "%Y-%m-%d")
    except: inicio = datetime.now()
    try: duracion = int(float(grupo_data['SemanasDuracion']))
    except: duracion = 25
    
    mbase = float(grupo_data.get('MontoBase', 400))
    minteres = float(grupo_data.get('MontoInteres', 430))

    hoy = datetime.now()
    dias_pasados = (hoy - inicio).days
    semana_actual = max(0, dias_pasados // 7) + 1
    if semana_actual > duracion: semana_actual = duracion
    
    df_m = cargar_excel(FILE_MIEMBROS, {"NombreGrupo":"", "DNI_Usuario":"", "Turno":"0", "Tipo":"Completo"})
    df_p = cargar_excel(FILE_PAGOS, {"Grupo":"", "Estado":""})
    
    num_integrantes = len(df_m[df_m['NombreGrupo'] == nombre_grupo])
    por_revisar = len(df_p[(df_p['Grupo'] == nombre_grupo) & (df_p['Estado'] == 'Pendiente')])
    
    return {
        "Inicio": inicio.strftime("%d/%m/%Y"),
        "Fin": (inicio + timedelta(weeks=duracion)).strftime("%d/%m/%Y"),
        "SemanaActual": f"{semana_actual} de {duracion}",
        "Integrantes": num_integrantes,
        "PorRevisar": por_revisar,
        "FechaRaw": inicio,
        "ConfigBase": mbase,
        "ConfigInteres": minteres,
        "Duracion": duracion
    }

def generar_calendario_usuario(dni_usuario):
    df_miembros = cargar_excel(FILE_MIEMBROS, {"NombreGrupo":"", "DNI_Usuario":"", "Turno":"0", "Tipo":"Completo"})
    df_grupos = cargar_excel(FILE_GRUPOS, {"NombreGrupo":"", "FechaInicio":"", "SemanasDuracion":"25", "MontoBase":"400", "MontoInteres":"430"})
    df_pagos = cargar_excel(FILE_PAGOS, {"Fecha":"", "DNI":"", "Grupo":"", "Monto":"", "Estado":"", "SemanaPagada":""})
    
    fila_miembro = df_miembros[df_miembros['DNI_Usuario'] == dni_usuario]
    if fila_miembro.empty: return [], "Sin Grupo", "Completo"
    
    datos_miembro = fila_miembro.iloc[0]
    grupo = datos_miembro['NombreGrupo']
    try: turno = int(float(datos_miembro.get('Turno', 0)))
    except: turno = 0
    
    tipo_participacion = datos_miembro.get('Tipo', 'Completo')
    factor = 0.5 if tipo_participacion == 'Medio' else 1.0
    
    grupo_subset = df_grupos[df_grupos['NombreGrupo'] == grupo]
    if grupo_subset.empty: return [], "Grupo Error", tipo_participacion

    datos_grupo = grupo_subset.iloc[0]
    try: inicio = datetime.strptime(limpiar_fecha(datos_grupo['FechaInicio']), "%Y-%m-%d")
    except: return [], "Fecha Inválida", tipo_participacion
    try: duracion = int(float(datos_grupo['SemanasDuracion']))
    except: duracion = 25
    
    try: base_config = float(datos_grupo.get('MontoBase', 400))
    except: base_config = 400.0
    try: interes_config = float(datos_grupo.get('MontoInteres', 430))
    except: interes_config = 430.0

    monto_base_usuario = base_config * factor
    monto_interes_usuario = interes_config * factor
    
    calendario = []
    hoy = datetime.now()
    mis_pagos = df_pagos[(df_pagos['DNI'] == dni_usuario) & (df_pagos['Grupo'] == grupo)]
    
    try: total_pagado_global = mis_pagos[mis_pagos['Estado'] == 'Aprobado']['Monto'].astype(float).sum()
    except: total_pagado_global = 0
    
    try: total_pendiente_global = mis_pagos[mis_pagos['Estado'] == 'Pendiente']['Monto'].astype(float).sum()
    except: total_pendiente_global = 0
    
    acumulado_teorico = 0
    
    for i in range(duracion):
        num_semana = i + 1
        fecha_pago = inicio + timedelta(weeks=i)
        
        monto_semana = monto_interes_usuario if (turno > 0 and num_semana > turno) else monto_base_usuario
        acumulado_teorico += monto_semana
        
        estado = "grey"
        if total_pagado_global >= acumulado_teorico:
            estado = "green"
        elif (total_pagado_global + total_pendiente_global) >= acumulado_teorico:
            estado = "orange"
        elif total_pagado_global >= (acumulado_teorico - monto_semana) and total_pagado_global < acumulado_teorico:
             estado = "yellow"
        elif fecha_pago < hoy:
            estado = "red"
        else:
            estado = "grey"

        calendario.append({"Semana": num_semana, "Fecha": fecha_pago.strftime("%d/%m"), "Monto": monto_semana, "Estado": estado})
    
    return calendario, grupo, tipo_participacion

# --- INICIO DE APP ---
if 'usuario' not in st.session_state: st.session_state.usuario = None
if 'grupo_seleccionado' not in st.session_state: st.session_state.grupo_seleccionado = None

with st.sidebar:
    st.title("🏛️ PANDERO")
    if st.session_state.usuario:
        st.write(f"Hola, **{st.session_state.get('nombre_pila', 'Admin')}**")
        if st.button("Cerrar Sesión", use_container_width=True):
            st.session_state.usuario = None; st.session_state.grupo_seleccionado = None; st.rerun()

# 1. LOGIN
if st.session_state.usuario is None:
    c1, c2 = st.columns(2)
    with c1:
        dni = st.text_input("DNI Socio")
        if st.button("Ingresar"):
            df = cargar_excel(FILE_USUARIOS, {"Nombre":"", "DNI":""})
            if dni in df['DNI'].values:
                st.session_state.usuario = dni; st.session_state.rol = 'usuario'
                st.session_state.nombre_pila = df[df['DNI']==dni].iloc[0]['Nombre'].split(" ")[0]
                st.rerun()
            else: st.error("DNI no existe")
    with c2:
        pk = st.text_input("Clave Admin", type="password")
        if st.button("Acceder"):
            if pk == "admin123":
                st.session_state.usuario = "ADMIN"; st.session_state.rol = 'admin'; st.session_state.nombre_pila = "Admin"
                st.rerun()

# 2. ADMIN
elif st.session_state.rol == 'admin':
    if st.session_state.grupo_seleccionado is None:
        st.header("Mis Panderos")
        with st.expander("Crear Nuevo Grupo"):
            c1, c2 = st.columns(2)
            n_nuevo = c1.text_input("Nombre Grupo")
            f_nuevo = c2.date_input("Fecha Inicio")
            st.write("Configuración")
            c3, c4, c5 = st.columns(3)
            duracion_semanas = c3.number_input("Duración (Semanas)", min_value=1, value=20, step=1)
            m_base = c4.number_input("Cuota Base", value=400.0)
            m_interes = c5.number_input("Cuota con Interés", value=430.0)
            if st.button("Crear Grupo", use_container_width=True):
                if n_nuevo:
                    df = cargar_excel(FILE_GRUPOS, {"NombreGrupo":"", "FechaInicio":"", "SemanasDuracion":"", "MontoBase":"", "MontoInteres":""})
                    if n_nuevo not in df['NombreGrupo'].values:
                        nuevo = pd.DataFrame([{"NombreGrupo": n_nuevo, "FechaInicio": f_nuevo, "SemanasDuracion": duracion_semanas, "MontoBase": m_base, "MontoInteres": m_interes}])
                        guardar_excel(pd.concat([df, nuevo]), FILE_GRUPOS); st.success("Creado!"); st.rerun()
                    else: st.error("Ese nombre ya existe")
        
        df_g = cargar_excel(FILE_GRUPOS, {"NombreGrupo":""})
        if not df_g.empty:
            cols = st.columns(3)
            for idx, row in df_g.iterrows():
                nom = row['NombreGrupo']
                stt = calcular_detalle_grupo(nom)
                if stt:
                    with cols[idx%3]:
                        st.markdown(f"""<div class="group-card"><div class="card-header">{nom}</div>
                        <div class="card-stat">Socios: <strong>{stt['Integrantes']}</strong></div>
                        <div class="card-stat">Duración: <strong>{stt['Duracion']} sem</strong></div>
                        <div class="card-stat">Revisión: <strong class="highlight-green">{stt['PorRevisar']}</strong></div></div>""", unsafe_allow_html=True)
                        if st.button(f"Gestionar {nom}", key=nom, use_container_width=True):
                            st.session_state.grupo_seleccionado = nom; st.rerun()
        else: st.info("No hay grupos aún.")
    else:
        grupo = st.session_state.grupo_seleccionado
        datos_grupo_actual = calcular_detalle_grupo(grupo)
        if st.button("⬅️ Volver", type="secondary"): st.session_state.grupo_seleccionado = None; st.rerun()
        st.title(f"Gestión: {grupo}")
        
        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["👥 Miembros", "➕ Inscribir", "🎲 Sorteo", "⚙️ Ajustes", "💰 Gestión Pagos", "📄 Reportes"])
        
        with tab1: # MIEMBROS
            df_m = cargar_excel(FILE_MIEMBROS, {"NombreGrupo":"", "DNI_Usuario":"", "Turno":"", "Tipo":""})
            df_u = cargar_excel(FILE_USUARIOS, {"Nombre":"", "DNI":""})
            mis_miembros = df_m[df_m['NombreGrupo']==grupo].copy()
            if not mis_miembros.empty:
                mis_miembros['TurnoNum'] = pd.to_numeric(mis_miembros['Turno'], errors='coerce').fillna(0)
                mis_miembros = mis_miembros.sort_values(by='TurnoNum')
                data = pd.merge(mis_miembros, df_u, left_on="DNI_Usuario", right_on="DNI")
                for _, r in data.iterrows():
                    turno = int(float(r.get('Turno', 0)))
                    cal, _, _ = generar_calendario_usuario(r['DNI'])
                    deuda = sum(1 for c in cal if c['Estado']=='red')
                    tag = '½' if r.get('Tipo') == 'Medio' else ''
                    with st.expander(f"Turno {turno} | {'🔴' if deuda>0 else '🟢'} {r['Nombre']} {tag}"):
                        c1, c2 = st.columns([3, 1])
                        c1.write(f"DNI: {r['DNI']} | Deuda: {deuda}"); c1.markdown(f"[📲 WhatsApp](https://wa.me/?text=Hola%20{r['Nombre']})")
                        c2.metric("Total Pagado", f"S/. {sum(c['Monto'] for c in cal if c['Estado'] == 'green')}")
                        df_vis = pd.DataFrame(cal)[['Semana','Fecha','Monto','Estado']]
                        df_vis['Monto'] = df_vis['Monto'].apply(lambda x: f"S/. {x:.2f}")
                        mapa = {'red': '🔴', 'green': '🟢', 'grey': '⚪', 'orange': '🟠', 'yellow': '🟡'}
                        df_vis['Estado'] = df_vis['Estado'].map(mapa)
                        st.dataframe(df_vis, hide_index=True, use_container_width=True)
            else: st.info("Sin miembros.")

        with tab2: # INSCRIBIR
            st.subheader("Inscribir Socio")
            df_u = cargar_excel(FILE_USUARIOS, {"Nombre":"", "DNI":""})
            if not df_u.empty:
                busqueda = st.text_input("🔍 Buscar Socio (Nombre o DNI)", placeholder="Escribe para filtrar...")
                df_filtrado = df_u[df_u['Nombre'].str.contains(busqueda, case=False) | df_u['DNI'].str.contains(busqueda)] if busqueda else df_u
                if not df_filtrado.empty:
                    opciones = df_filtrado.apply(lambda x: f"{x['DNI']} - {x['Nombre']}", axis=1)
                    sel_u = st.selectbox("Seleccionar de la lista:", opciones)
                    c_t1, c_t2 = st.columns(2)
                    sel_t = c_t1.number_input("Turno Asignado", 1, int(datos_grupo_actual['Duracion']), 1)
                    es_medio = c_t2.checkbox("¿Comparte turno? (Paga 50%)")
                    if st.button("Guardar Inscripción"):
                        dni = sel_u.split(" - ")[0]
                        tp = "Medio" if es_medio else "Completo"
                        df_m = cargar_excel(FILE_MIEMBROS, {"NombreGrupo":"", "DNI_Usuario":"", "Turno":"", "Tipo":""})
                        if df_m[(df_m['NombreGrupo']==grupo) & (df_m['DNI_Usuario']==dni)].empty:
                            guardar_excel(pd.concat([df_m, pd.DataFrame([{"NombreGrupo":grupo, "DNI_Usuario":dni, "Turno":str(int(sel_t)), "Tipo":tp}])]), FILE_MIEMBROS)
                            st.success("Inscrito"); st.rerun()
                        else: st.error("Ya existe")
                else: st.warning("No se encontraron coincidencias.")
            else: st.error("No hay usuarios.")

        with tab3: # SORTEO
            st.subheader("🎲 Sorteo Automático")
            if st.button("¡Realizar Sorteo Ahora!"):
                df_m = cargar_excel(FILE_MIEMBROS, {"NombreGrupo":"", "DNI_Usuario":"", "Turno":""})
                indices = df_m.index[df_m['NombreGrupo'] == grupo].tolist()
                if indices:
                    turnos = list(range(1, len(indices) + 1)); random.shuffle(turnos)
                    for i, idx_row in enumerate(indices): df_m.at[idx_row, 'Turno'] = str(turnos[i])
                    guardar_excel(df_m, FILE_MIEMBROS); st.success("Sorteo Completado!"); st.balloons()
                else: st.warning("No hay miembros.")

        with tab4: # AJUSTES
            st.subheader("🛠️ Ajustes")
            nueva_fecha = st.date_input("Fecha Inicio", value=datos_grupo_actual['FechaRaw'])
            if st.button("Actualizar Fecha"):
                df_g = cargar_excel(FILE_GRUPOS, {"NombreGrupo":"", "FechaInicio":""})
                idx = df_g.index[df_g['NombreGrupo'] == grupo].tolist()[0]
                df_g.at[idx, 'FechaInicio'] = nueva_fecha
                guardar_excel(df_g, FILE_GRUPOS); st.success("Hecho"); st.rerun()
            st.divider()
            st.write("Edición Manual")
            df_m = cargar_excel(FILE_MIEMBROS, {"NombreGrupo":"", "DNI_Usuario":"", "Turno":"", "Tipo":""})
            df_u = cargar_excel(FILE_USUARIOS, {"Nombre":"", "DNI":""})
            mask = df_m['NombreGrupo'] == grupo
            df_view = pd.merge(df_m[mask], df_u[['DNI', 'Nombre']], left_on='DNI_Usuario', right_on='DNI', how='left')
            if not df_view.empty:
                df_edt = df_view[['Nombre', 'DNI_Usuario', 'Turno', 'Tipo']].copy()
                df_edt['Turno'] = pd.to_numeric(df_edt['Turno'])
                edt = st.data_editor(df_edt, column_config={"Nombre":st.column_config.TextColumn(disabled=True), "DNI_Usuario":st.column_config.TextColumn(disabled=True), "Turno":st.column_config.NumberColumn(min_value=1)}, hide_index=True, use_container_width=True)
                if st.button("Guardar Cambios"):
                    for _, r in edt.iterrows():
                        idx = df_m.index[(df_m['NombreGrupo']==grupo) & (df_m['DNI_Usuario']==r['DNI_Usuario'])]
                        if not idx.empty: df_m.at[idx[0], 'Turno'] = r['Turno']; df_m.at[idx[0], 'Tipo'] = r['Tipo']
                    guardar_excel(df_m, FILE_MIEMBROS); st.success("Guardado")

        with tab5: # GESTIÓN PAGOS (RENOVADO)
            subtab_a, subtab_b = st.tabs(["🔍 Revisar Pendientes", "✍️ Registro Manual (Sin Foto)"])
            
            with subtab_a: # VALIDAR NORMAL
                df_p = cargar_excel(FILE_PAGOS, {"Fecha":"", "DNI":"", "Grupo":"", "Monto":"", "Estado":"", "Foto":"", "SemanaPagada":""})
                df_u = cargar_excel(FILE_USUARIOS, {"Nombre":"", "DNI":""})
                pendientes = df_p[(df_p['Grupo'] == grupo) & (df_p['Estado'] == 'Pendiente')]
                if not pendientes.empty:
                    view_pago = pd.merge(pendientes, df_u, on="DNI", how="left")
                    for idx, row in view_pago.iterrows():
                        with st.container(border=True):
                            c1, c2, c3 = st.columns([1, 2, 1])
                            path = os.path.join(CARPETA_FOTOS, str(row['Foto']))
                            if os.path.exists(path): c1.image(path, use_container_width=True)
                            else: c1.error("Sin imagen")
                            c2.markdown(f"**Socio:** {row['Nombre']}"); c2.markdown(f"**Cuota:** {row.get('SemanaPagada')}"); c2.markdown(f"**Monto:** S/. {row['Monto']}")
                            c3.write("¿Aprobar?")
                            mask = (df_p['DNI'] == row['DNI']) & (df_p['Fecha'] == row['Fecha']) & (df_p['Monto'] == row['Monto']) & (df_p['Estado'] == 'Pendiente')
                            if c3.button("✅", key=f"y_{idx}"):
                                df_p.at[df_p[mask].index[0], 'Estado'] = 'Aprobado'; guardar_excel(df_p, FILE_PAGOS); st.rerun()
                            if c3.button("❌", key=f"n_{idx}"):
                                df_p.at[df_p[mask].index[0], 'Estado'] = 'Rechazado'; guardar_excel(df_p, FILE_PAGOS); st.rerun()
                else: st.info("No hay pagos pendientes de revisión.")
            
            with subtab_b: # REGISTRO MANUAL
                st.warning("⚠️ Usa esto solo si recibiste el dinero en efectivo o por fuera.")
                df_u = cargar_excel(FILE_USUARIOS, {"Nombre":"", "DNI":""})
                
                # 1. Seleccionar Usuario
                opciones_manual = df_u.apply(lambda x: f"{x['DNI']} - {x['Nombre']}", axis=1)
                sel_manual = st.selectbox("Seleccionar Socio para registrar pago:", opciones_manual)
                
                if sel_manual:
                    dni_manual = sel_manual.split(" - ")[0]
                    # 2. Calcular Semanas Pendientes de ese usuario
                    cal_manual, _, _ = generar_calendario_usuario(dni_manual)
                    # Filtramos solo las que no estan pagadas
                    semanas_pendientes = [f"Semana {s['Semana']} ({s['Fecha']})" for s in cal_manual if s['Estado'] != 'green']
                    
                    if semanas_pendientes:
                        sem_man = st.selectbox("Semana a pagar:", semanas_pendientes)
                        monto_man = st.number_input("Monto Recibido (S/.)", min_value=0.0, step=10.0)
                        
                        if st.button("💾 Registrar y Aprobar Manualmente"):
                            if monto_man > 0:
                                df_p = cargar_excel(FILE_PAGOS, {"Fecha":"", "DNI":"", "Grupo":"", "Monto":"", "Estado":"", "Foto":"", "SemanaPagada":""})
                                nuevo_pago = pd.DataFrame([{
                                    "Fecha": datetime.now().strftime("%Y-%m-%d"),
                                    "DNI": dni_manual,
                                    "Grupo": grupo,
                                    "Monto": str(monto_man),
                                    "Estado": "Aprobado", # Directo a aprobado
                                    "Foto": "Pago_Manual_Admin",
                                    "SemanaPagada": sem_man
                                }])
                                guardar_excel(pd.concat([df_p, nuevo_pago], ignore_index=True), FILE_PAGOS)
                                st.success("Pago registrado correctamente."); time.sleep(1.5); st.rerun()
                            else:
                                st.error("El monto debe ser mayor a 0")
                    else:
                        st.success("Este usuario ya pagó todo.")

        with tab6: # REPORTES
            st.subheader("📄 Reportes del Grupo")
            st.write("Genera un documento oficial.")
            if st.button("Generar Reporte PDF"):
                df_m = cargar_excel(FILE_MIEMBROS, {"NombreGrupo":"", "DNI_Usuario":"", "Turno":""})
                df_u = cargar_excel(FILE_USUARIOS, {"Nombre":"", "DNI":""})
                mis_miembros = df_m[df_m['NombreGrupo']==grupo]
                datos_reporte = []
                if not mis_miembros.empty:
                    merged = pd.merge(mis_miembros, df_u, left_on="DNI_Usuario", right_on="DNI")
                    for _, r in merged.iterrows():
                        cal, _, _ = generar_calendario_usuario(r['DNI'])
                        deuda = sum(1 for c in cal if c['Estado']=='red')
                        pagado = sum(c['Monto'] for c in cal if c['Estado'] == 'green')
                        datos_reporte.append({"Nombre": r['Nombre'], "Turno": r.get('Turno', '-'), "Pagado": pagado, "Deuda": deuda})
                    pdf_bytes = crear_reporte_pdf(grupo, datos_reporte)
                    b64 = base64.b64encode(pdf_bytes).decode()
                    href = f'<a href="data:application/octet-stream;base64,{b64}" download="Reporte_{grupo}.pdf" style="text-decoration:none; background-color:#FF4B4B; color:white; padding:10px 20px; border-radius:5px;">📥 Descargar PDF</a>'
                    st.markdown(href, unsafe_allow_html=True)
                else: st.error("No hay datos.")

# 3. USUARIO
elif st.session_state.rol == 'usuario':
    st.title(f"Hola, {st.session_state.nombre_pila}")
    
    # ALERTAS
    df_alertas = cargar_excel(FILE_PAGOS, {"DNI":"", "Estado":""})
    alertas_rechazo = df_alertas[(df_alertas['DNI'] == st.session_state.usuario) & (df_alertas['Estado'] == 'Rechazado')]
    if not alertas_rechazo.empty:
        st.error(f"⚠️ Tienes {len(alertas_rechazo)} pago(s) RECHAZADO(S) por el administrador. Revisa y vuelve a subir.")
    
    cal, nom_g, tipo_p = generar_calendario_usuario(st.session_state.usuario)
    if cal:
        st.caption(f"Grupo: {nom_g} | Participación: {tipo_p}")
        c1, c2 = st.columns([2,1])
        with c1:
            for s in cal:
                clr = {'green':'#2ecc71','red':'#e74c3c','orange':'#f39c12','yellow':'#f1c40f','grey':'#555'}[s['Estado']]
                st.markdown(f"""<div class="user-week-card" style="border-left-color:{clr}">
                <div><strong>Semana {s['Semana']}</strong><br><small style="color:#aaa">{s['Fecha']}</small></div>
                <div style="font-size:18px">S/. {s['Monto']:.2f}</div></div>""", unsafe_allow_html=True)
        with c2:
            st.container(border=True).write("### Pagar Cuota")
            with st.form("form_pago", clear_on_submit=True):
                opciones_semanas = [f"Semana {s['Semana']} ({s['Fecha']})" for s in cal if s['Estado'] != 'green']
                if opciones_semanas:
                    semana_elegida = st.selectbox("¿Qué semana abonas?", opciones_semanas)
                    monto_pago = st.number_input("Monto (S/.)", 0.0, 5000.0, 0.0, step=10.0)
                    uploaded = st.file_uploader("Voucher")
                    enviado = st.form_submit_button("Enviar Pago")
                    if enviado:
                        if uploaded and monto_pago > 0:
                            df_p = cargar_excel(FILE_PAGOS, {"Fecha":"", "DNI":"", "Grupo":"", "Monto":"", "Estado":"", "Foto":"", "SemanaPagada":""})
                            fecha = datetime.now().strftime("%Y-%m-%d")
                            path_u = os.path.join(CARPETA_FOTOS, str(st.session_state.usuario), str(nom_g))
                            if not os.path.exists(path_u): os.makedirs(path_u)
                            try: ns = semana_elegida.split(" ")[1]
                            except: ns = "X"
                            fname = f"Semana_{ns}_{datetime.now().strftime('%H%M%S')}.png"
                            full_path = os.path.join(path_u, fname)
                            with open(full_path, "wb") as f: f.write(uploaded.getbuffer())
                            rel_path = os.path.join(str(st.session_state.usuario), str(nom_g), fname)
                            guardar_excel(pd.concat([df_p, pd.DataFrame([{
                                "Fecha": fecha, "DNI": st.session_state.usuario, "Grupo": nom_g,
                                "Monto": str(monto_pago), "Estado": "Pendiente", "Foto": rel_path, "SemanaPagada": semana_elegida
                            }])], ignore_index=True), FILE_PAGOS)
                            st.success("Enviado ✅"); time.sleep(2); st.rerun()
                        else: st.error("Completa todo")
                else: st.success("🎉 ¡Felicidades! Pagaste todo.")
    else: st.warning("Sin grupo asignado.")