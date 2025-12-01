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

# --- CONFIGURACIÓN GENERAL ---
st.set_page_config(page_title="Sistema Pandero", page_icon="💰", layout="wide")

# --- CONEXIÓN GOOGLE SHEETS ---
def get_google_sheet_client():
    # Usamos los secretos de Streamlit para no poner la contraseña en el código
    creds_dict = st.secrets["gcp_service_account"]
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client

def conectar_db(hoja_nombre):
    try:
        client = get_google_sheet_client()
        # Abre el archivo por nombre
        sh = client.open("BASE_DATOS_PANDERO") 
        return sh.worksheet(hoja_nombre)
    except Exception as e:
        st.error(f"Error conectando a Google Sheets: {e}")
        st.stop()

# --- FUNCIONES DE CARGA Y GUARDADO (NUBE) ---
def cargar_datos(hoja):
    worksheet = conectar_db(hoja)
    data = worksheet.get_all_records()
    if not data:
        return pd.DataFrame()
    return pd.DataFrame(data).astype(str)

def guardar_fila(hoja, dict_datos):
    worksheet = conectar_db(hoja)
    # Convertir dict a lista de valores respetando el orden no es seguro con diccionarios
    # Mejor: agregar fila directamente. gspread lo pone al final.
    valores = list(dict_datos.values())
    worksheet.append_row(valores)

def actualizar_celda(hoja, columna_filtro, valor_filtro, columna_a_cambiar, nuevo_valor):
    # Esta función busca una fila y actualiza un valor (ej: Aprobar pago)
    worksheet = conectar_db(hoja)
    cell = worksheet.find(valor_filtro) # Busca por ejemplo el DNI o ID
    # Esto es una simplificación. Para producción robusta se usa row id.
    # Para este ejemplo, recargaremos todo el DF, modificaremos y reescribiremos (más lento pero seguro para novatos)
    pass 

# --- LÓGICA HÍBRIDA (MEJORADA PARA ESTABILIDAD) ---
# Para no complicar con updates de celdas especificas en GSheets (que es complejo),
# usaremos la estrategia: Descargar Todo -> Modificar en Pandas -> Borrar Hoja -> Subir Todo
# Es menos eficiente pero infalible para empezar.

def cargar_df(hoja):
    worksheet = conectar_db(hoja)
    data = worksheet.get_all_records()
    return pd.DataFrame(data).astype(str)

def guardar_df_completo(hoja, df):
    worksheet = conectar_db(hoja)
    worksheet.clear() # Borra todo
    # Pone los headers
    worksheet.update([df.columns.values.tolist()] + df.values.tolist())

# --- VARIABLES CONSTANTES ---
# Nombres de las pestañas en tu Google Sheet
TAB_USUARIOS = 'usuarios'
TAB_GRUPOS = 'grupos'
TAB_MIEMBROS = 'miembros'
TAB_PAGOS = 'pagos'

# --- UTILS FECHAS ---
def limpiar_fecha(fecha_str):
    return str(fecha_str).split(" ")[0]

# --- LÓGICA DE NEGOCIO (ADAPTADA A SHEETS) ---

def calcular_detalle_grupo(nombre_grupo):
    df_g = cargar_df(TAB_GRUPOS)
    if df_g.empty: return None
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
    
    df_m = cargar_df(TAB_MIEMBROS)
    df_p = cargar_df(TAB_PAGOS)
    
    num_integrantes = len(df_m[df_m['NombreGrupo'] == nombre_grupo]) if not df_m.empty else 0
    por_revisar = 0
    if not df_p.empty:
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
    df_m = cargar_df(TAB_MIEMBROS)
    df_g = cargar_df(TAB_GRUPOS)
    df_p = cargar_df(TAB_PAGOS)
    
    if df_m.empty: return [], "Sin Grupo", "Completo"
    
    fila_miembro = df_m[df_m['DNI_Usuario'] == dni_usuario]
    if fila_miembro.empty: return [], "Sin Grupo", "Completo"
    
    datos_miembro = fila_miembro.iloc[0]
    grupo = datos_miembro['NombreGrupo']
    try: turno = int(float(datos_miembro.get('Turno', 0)))
    except: turno = 0
    
    tipo_participacion = datos_miembro.get('Tipo', 'Completo')
    factor = 0.5 if tipo_participacion == 'Medio' else 1.0
    
    grupo_subset = df_g[df_g['NombreGrupo'] == grupo]
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
    
    # Filtros seguros
    mis_pagos = pd.DataFrame()
    if not df_p.empty:
        mis_pagos = df_p[(df_p['DNI'] == dni_usuario) & (df_p['Grupo'] == grupo)]
    
    total_pagado_global = 0
    total_pendiente_global = 0
    
    if not mis_pagos.empty:
        try: total_pagado_global = mis_pagos[mis_pagos['Estado'] == 'Aprobado']['Monto'].astype(float).sum()
        except: pass
        try: total_pendiente_global = mis_pagos[mis_pagos['Estado'] == 'Pendiente']['Monto'].astype(float).sum()
        except: pass
    
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

# --- INTERFAZ ---

if 'usuario' not in st.session_state: st.session_state.usuario = None

with st.sidebar:
    st.title("🏛️ PANDERO")
    if st.session_state.usuario:
        st.success(f"Conectado: {st.session_state.nombre_pila}")
        if st.button("Cerrar Sesión"):
            st.session_state.usuario = None
            st.rerun()

# 1. LOGIN MEJORADO (Con tecla Enter y Botones Rojos)
if st.session_state.usuario is None:
    c1, c2 = st.columns(2)
    
    with c1:
        st.subheader("👤 Acceso Socio")
        # Usamos 'form' para que al dar Enter funcione
        with st.form("login_socio"):
            dni = st.text_input("Ingresa tu DNI")
            # type="primary" pone el botón ROJO
            btn_ingresar = st.form_submit_button("Ingresar", type="primary", use_container_width=True)
            
            if btn_ingresar:
                df_u = cargar_df(TAB_USUARIOS)
                if not df_u.empty and dni in df_u['DNI'].values:
                    st.session_state.usuario = dni
                    st.session_state.rol = 'usuario'
                    st.session_state.nombre_pila = df_u[df_u['DNI']==dni].iloc[0]['Nombre']
                    st.rerun()
                else:
                    st.error("❌ DNI no encontrado en la base de datos.")

    with c2:
        st.subheader("🛡️ Acceso Admin")
        with st.form("login_admin"):
            pk = st.text_input("Contraseña", type="password")
            btn_admin = st.form_submit_button("Acceder", type="primary", use_container_width=True)
            
            if btn_admin:
                if pk == "admin123":
                    st.session_state.usuario = "ADMIN"
                    st.session_state.rol = 'admin'
                    st.session_state.nombre_pila = "Admin"
                    st.rerun()
                else:
                    st.error("❌ Contraseña incorrecta")
# 2. ADMIN
elif st.session_state.rol == 'admin':
    if 'grupo_sel' not in st.session_state: st.session_state.grupo_sel = None
    
    if st.session_state.grupo_sel is None:
        st.header("Mis Panderos (En la Nube)")
        with st.expander("Crear Nuevo Grupo"):
            c1, c2 = st.columns(2)
            n_nuevo = c1.text_input("Nombre Grupo")
            f_nuevo = c2.date_input("Fecha Inicio")
            c3, c4, c5 = st.columns(3)
            duracion = c3.number_input("Semanas", 1, 50, 20)
            m_base = c4.number_input("Base", 400.0)
            m_int = c5.number_input("Con Interés", 430.0)
            
            if st.button("Crear Grupo"):
                df_g = cargar_df(TAB_GRUPOS)
                if not df_g.empty and n_nuevo in df_g['NombreGrupo'].values:
                    st.error("Ya existe")
                else:
                    nuevo = {"NombreGrupo": n_nuevo, "FechaInicio": str(f_nuevo), "SemanasDuracion": duracion, "MontoBase": m_base, "MontoInteres": m_int}
                    df_new = pd.concat([df_g, pd.DataFrame([nuevo])], ignore_index=True)
                    guardar_df_completo(TAB_GRUPOS, df_new)
                    st.success("Creado"); st.rerun()
        
        df_g = cargar_df(TAB_GRUPOS)
        if not df_g.empty:
            for idx, row in df_g.iterrows():
                nom = row['NombreGrupo']
                if st.button(f"Gestionar {nom}", key=nom):
                    st.session_state.grupo_sel = nom
                    st.rerun()
        else: st.info("No hay grupos.")
    else:
        grupo = st.session_state.grupo_sel
        if st.button("⬅️ Volver"): st.session_state.grupo_sel = None; st.rerun()
        st.title(f"Gestión: {grupo}")
        
        t1, t2, t3, t4 = st.tabs(["Miembros", "Inscribir", "Pagos", "Reportes"])
        
        with t1: # MIEMBROS
            df_m = cargar_df(TAB_MIEMBROS)
            df_u = cargar_df(TAB_USUARIOS)
            mis_m = df_m[df_m['NombreGrupo']==grupo]
            if not mis_m.empty and not df_u.empty:
                data = pd.merge(mis_m, df_u, left_on="DNI_Usuario", right_on="DNI")
                for _, r in data.iterrows():
                    cal, _, _ = generar_calendario_usuario(r['DNI'])
                    deuda = sum(1 for c in cal if c['Estado']=='red')
                    with st.expander(f"{r['Nombre']} (Turno {r['Turno']}) - Deuda: {deuda}"):
                        st.dataframe(pd.DataFrame(cal))
            else: st.info("Sin miembros")
            
        with t2: # INSCRIBIR
            st.write("Nuevo usuario")
            u_nom = st.text_input("Nombre Completo")
            u_dni = st.text_input("DNI")
            if st.button("Crear Usuario Nube"):
                df_u = cargar_df(TAB_USUARIOS)
                if u_dni and u_dni not in df_u['DNI'].values:
                    nuevo = pd.DataFrame([{"Nombre": u_nom, "DNI": u_dni, "Celular": ""}])
                    guardar_df_completo(TAB_USUARIOS, pd.concat([df_u, nuevo], ignore_index=True))
                    st.success("Usuario Creado")
                else: st.error("DNI ya existe")
            
            st.divider()
            st.write("Asignar a Grupo")
            df_u = cargar_df(TAB_USUARIOS)
            if not df_u.empty:
                sel_u = st.selectbox("Usuario", df_u['DNI'] + " - " + df_u['Nombre'])
                turno = st.number_input("Turno", 1, 50)
                if st.button("Inscribir"):
                    dni = sel_u.split(" - ")[0]
                    df_m = cargar_df(TAB_MIEMBROS)
                    nuevo = pd.DataFrame([{"NombreGrupo": grupo, "DNI_Usuario": dni, "Turno": turno, "Tipo": "Completo"}])
                    guardar_df_completo(TAB_MIEMBROS, pd.concat([df_m, nuevo], ignore_index=True))
                    st.success("Inscrito"); st.rerun()

        with t3: # PAGOS
            df_p = cargar_df(TAB_PAGOS)
            df_u = cargar_df(TAB_USUARIOS)
            pendientes = df_p[(df_p['Grupo'] == grupo) & (df_p['Estado'] == 'Pendiente')]
            
            if not pendientes.empty:
                view = pd.merge(pendientes, df_u, on="DNI")
                for idx, row in view.iterrows():
                    st.info(f"Pago de {row['Nombre']} - S/. {row['Monto']}")
                    # Fotos temporales no se ven si reinicia el server, aqui iria logica de link
                    c1, c2 = st.columns(2)
                    if c1.button("✅ Aprobar", key=f"y_{idx}"):
                        # Actualizar estado
                        mask = (df_p['DNI'] == row['DNI']) & (df_p['Fecha'] == row['Fecha']) & (df_p['Monto'] == row['Monto'])
                        idx_orig = df_p[mask].index[0]
                        df_p.at[idx_orig, 'Estado'] = 'Aprobado'
                        guardar_df_completo(TAB_PAGOS, df_p)
                        st.success("Hecho"); st.rerun()
            else: st.info("Nada pendiente")

# 3. USUARIO
elif st.session_state.rol == 'usuario':
    st.title(f"Hola, {st.session_state.nombre_pila}")
    cal, nom_g, tipo_p = generar_calendario_usuario(st.session_state.usuario)
    if cal:
        st.info(f"Grupo: {nom_g}")
        st.dataframe(pd.DataFrame(cal)[['Semana','Fecha','Monto','Estado']])
        
        with st.form("pagar"):
            monto = st.number_input("Monto", 0.0)
            # Foto es decorativa en esta versión simple de nube sin storage externo
            st.file_uploader("Voucher") 
            if st.form_submit_button("Reportar Pago"):
                df_p = cargar_df(TAB_PAGOS)
                nuevo = pd.DataFrame([{
                    "Fecha": datetime.now().strftime("%Y-%m-%d"),
                    "DNI": st.session_state.usuario,
                    "Grupo": nom_g,
                    "Monto": str(monto),
                    "Estado": "Pendiente",
                    "Foto": "Pendiente_Storage", # Pendiente implementar Cloudinary
                    "SemanaPagada": "Varias"
                }])
                guardar_df_completo(TAB_PAGOS, pd.concat([df_p, nuevo], ignore_index=True))
                st.success("Enviado"); st.rerun()
    else: st.warning("Sin grupo")