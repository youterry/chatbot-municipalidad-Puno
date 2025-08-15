import os
from dotenv import load_dotenv
import google.generativeai as genai
from flask import Flask, request, jsonify
from flask_cors import CORS
import re 
import logging

# Configurar logging para ver mensajes de depuración
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Carga las variables de entorno desde el archivo .env
load_dotenv() 

app = Flask(__name__)
CORS(app) 

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

model = genai.GenerativeModel('gemini-2.5-flash-lite') 

# --- Historial de Conversación (Memoria) ---
conversation_log = []

def add_to_conversation_log(role, text):
    """Añade un mensaje al historial de conversación."""
    conversation_log.append({"role": role, "parts": [{"text": text}]})
    # REDUCCIÓN DE TOKENS: Limita la longitud del historial a 6 (3 pares de user/model)
    max_history_length = 6 
    if len(conversation_log) > max_history_length:
        conversation_log[:] = conversation_log[-max_history_length:]

# --- LÓGICA DE CARGA DE PROCEDIMIENTOS TUPA ---

TUPA_DATA_DIR = os.path.join(os.path.dirname(__file__), 'tupa_data')
tupa_procedures = {} 

def load_tupa_data():
    """
    Carga los datos de los procedimientos TUPA desde archivos .txt.
    Asegura que el 'Titulo:' y 'Código:' sean capturados,
    y mejora el parseo de la 'Descripción del Servicio' para contenido multilínea.
    """
    logging.info(f"Ruta absoluta del directorio TUPA_DATA_DIR: {os.path.abspath(TUPA_DATA_DIR)}")

    if not os.path.exists(TUPA_DATA_DIR):
        logging.error(f"Error: El directorio {TUPA_DATA_DIR} no existe. Asegúrate de que la carpeta 'tupa_data' esté en el mismo nivel que 'app.py'.")
        return
    
    if not os.path.isdir(TUPA_DATA_DIR):
        logging.error(f"Error: {TUPA_DATA_DIR} no es un directorio.")
        return

    files_in_dir = [f for f in os.listdir(TUPA_DATA_DIR) if f.endswith(".txt")]
    if not files_in_dir:
        logging.warning(f"El directorio '{TUPA_DATA_DIR}' está vacío o no contiene archivos .txt. No se cargarán datos TUPA.")
        return

    logging.info(f"Iniciando carga de datos TUPA desde: {TUPA_DATA_DIR}. Archivos encontrados: {files_in_dir}")

    section_keywords = {
        "Titulo:": "titulo",
        "Código:": "codigo",
        "Requisitos:": "requisitos",
        "Canales de atención:": "canales_atencion",
        "Pago por derecho de tramitación:": "pago_derecho_tramitacion",
        "Modalidad de pago:": "modalidad_pago",
        "Plazo:": "plazo",
        "Sedes y horarios de atención:": "sedes_horarios",
        "Unidad de organización donde se presenta la documentación:": "unidad_presentacion",
        "Unidad de organización responsable de aprobar la solicitud:": "unidad_aprobacion",
        "Consulta sobre el servicio:": "consulta_servicio"
    }
    
    # NUEVO: Lista de palabras clave para la descripción
    description_keywords_list = ["Descripción del procedimiento:", "Descripción del Servicio:"]

    sub_section_keywords = {
        "Monto -": "monto", 
        "Efectivo:": "efectivo", 
        "Teléfono:": "telefono_consulta", 
        "Anexo:": "anexo_consulta", 
        "Correo:": "correo_consulta" 
    }

    for filename in files_in_dir:
        file_path = os.path.join(TUPA_DATA_DIR, filename)
        logging.info(f"Procesando archivo: {filename}")
        
        procedure_data = {
            "titulo": "",
            "codigo": "", 
            "descripcion": "", 
            "requisitos": [],
            "canales_atencion": [],
            "pago_derecho_tramitacion": {"monto": "", "modalidad": []}, 
            "plazo": "",
            "sedes_horarios": [],
            "unidad_presentacion": "",
            "unidad_aprobacion": "",
            "consulta_servicio": {"telefono": "", "anexo": "", "correo": ""} 
        }
        
        current_main_section = None 
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                i = 0
                while i < len(lines):
                    line = lines[i].strip()
                    i += 1
                    
                    if not line: 
                        continue

                    matched_section = False
                    
                    # Primero, intenta coincidir con las palabras clave de descripción
                    for desc_kw in description_keywords_list:
                        if line.startswith(desc_kw):
                            current_main_section = "descripcion"
                            desc_content = []
                            # Si hay contenido en la misma línea después de la palabra clave
                            if line.replace(desc_kw, "", 1).strip():
                                desc_content.append(line.replace(desc_kw, "", 1).strip())
                            
                            temp_i = i # Usar un índice temporal para leer líneas adicionales de descripción
                            # Continúa leyendo hasta que encuentre una nueva sección principal o el final del archivo
                            while temp_i < len(lines) and \
                                  not any(lines[temp_i].strip().startswith(kw) for kw in section_keywords.keys()) and \
                                  not any(lines[temp_i].strip().startswith(dk) for dk in description_keywords_list):
                                if lines[temp_i].strip():
                                    desc_content.append(lines[temp_i].strip())
                                temp_i += 1
                            i = temp_i # Actualiza el índice principal
                            procedure_data["descripcion"] = " ".join(desc_content).strip()
                            logging.info(f"DEBUG_DESCRIPCION: Descripción parseada para '{filename}': '{procedure_data['descripcion']}'") 
                            matched_section = True
                            break # Salir del bucle de description_keywords_list una vez encontrada
                    
                    if matched_section: # Si ya se procesó la descripción, pasar a la siguiente línea
                        continue 

                    # Luego, verifica las otras palabras clave de sección principales
                    for keyword, attr_name in section_keywords.items():
                        if line.startswith(keyword):
                            current_main_section = attr_name
                            matched_section = True
                            
                            if keyword == "Titulo:":
                                procedure_data["titulo"] = line.replace(keyword, "", 1).strip()
                                logging.debug(f"  Título detectado: '{procedure_data['titulo']}'")
                                break
                            elif keyword == "Código:":
                                code_content = line.replace(keyword, "", 1).strip()
                                if not code_content and i < len(lines):
                                    next_line_content = lines[i].strip()
                                    if next_line_content and not any(next_line_content.startswith(kw) for kw in section_keywords.keys()):
                                        code_content = next_line_content
                                        i += 1 
                                procedure_data["codigo"] = code_content
                                logging.debug(f"  Código detectado: '{procedure_data['codigo']}'")
                                break
                            elif keyword == "Plazo:":
                                procedure_data["plazo"] = line.replace(keyword, "", 1).strip()
                                logging.debug(f"  Plazo detectado: '{procedure_data['plazo']}'")
                                break
                            # Las descripciones ya se manejan arriba, así que este 'elif attr_name == "descripcion":' se elimina.
                    
                    if matched_section:
                        continue 

                    if current_main_section:
                        def add_to_list_or_concat_last(target_list, current_line):
                            # Modificado para asegurar que no se añadan líneas vacías o nuevas secciones accidentalmente
                            if current_line.strip() and not any(current_line.startswith(kw) for kw in section_keywords.keys()) and not any(current_line.startswith(dk) for dk in description_keywords_list):
                                if re.match(r'^\d+\.-\s*.+', current_line) or re.match(r'^-+\s*.+', current_line): 
                                    target_list.append(current_line.strip())
                                else: 
                                    if target_list:
                                        target_list[-1] += " " + current_line.strip()
                                    else: 
                                        target_list.append(current_line.strip())

                        if current_main_section == "requisitos":
                            add_to_list_or_concat_last(procedure_data["requisitos"], line)
                        
                        elif current_main_section == "canales_atencion":
                            add_to_list_or_concat_last(procedure_data["canales_atencion"], line)
                        
                        elif current_main_section == "sedes_horarios":
                            add_to_list_or_concat_last(procedure_data["sedes_horarios"], line)
                        
                        elif current_main_section == "pago_derecho_tramitacion":
                            found_sub_section = False
                            for sub_keyword, sub_attr_name in sub_section_keywords.items():
                                if line.startswith(sub_keyword):
                                    if sub_attr_name == "monto":
                                        procedure_data["pago_derecho_tramitacion"][sub_attr_name] = line.replace(sub_keyword, "", 1).strip()
                                    found_sub_section = True
                                    break
                            if not found_sub_section and line.strip(): 
                                if line not in procedure_data["pago_derecho_tramitacion"]["modalidad"]:
                                    procedure_data["pago_derecho_tramitacion"]["modalidad"].append(line.strip())
                        
                        elif current_main_section == "modalidad_pago": 
                            if line.strip() and line not in procedure_data["pago_derecho_tramitacion"]["modalidad"]:
                                 procedure_data["pago_derecho_tramitacion"]["modalidad"].append(line.strip())

                        elif current_main_section == "unidad_presentacion":
                            if not any(line.startswith(kw) for kw in section_keywords.keys()) and not any(line.startswith(dk) for dk in description_keywords_list):
                                if not procedure_data["unidad_presentacion"]:
                                    procedure_data["unidad_presentacion"] = line.strip()
                                else:
                                    procedure_data["unidad_presentacion"] += " " + line.strip()
                        elif current_main_section == "unidad_aprobacion":
                            if not any(line.startswith(kw) for kw in section_keywords.keys()) and not any(line.startswith(dk) for dk in description_keywords_list):
                                if not procedure_data["unidad_aprobacion"]:
                                    procedure_data["unidad_aprobacion"] = line.strip()
                                else:
                                    procedure_data["unidad_aprobacion"] += " " + line.strip()

                        elif current_main_section == "consulta_servicio":
                            found_sub_section = False
                            for sub_keyword, sub_attr_name in sub_section_keywords.items():
                                if line.startswith(sub_keyword):
                                    if sub_attr_name in ["telefono_consulta", "anexo_consulta", "correo_consulta"]:
                                        procedure_data["consulta_servicio"][sub_attr_name.replace('_consulta', '')] = line.replace(sub_keyword, "", 1).strip()
                                        found_sub_section = True
                                        break
                            if not found_sub_section and line.strip(): 
                                if re.search(r'\b(tel(?:éfono)?|cel(?:ular)?|anexo)\b', line.lower()) or re.match(r'^\d{6,}', line.strip()):
                                    procedure_data["consulta_servicio"]["telefono"] = line.strip()
                                elif "@" in line:
                                    procedure_data["consulta_servicio"]["correo"] = line.strip()
                                elif "anexo" in line.lower():
                                    procedure_data["consulta_servicio"]["anexo"] = line.strip()

        except Exception as e:
            logging.error(f"Error al procesar el archivo {filename}: {e}")
            logging.error(f"Contenido actual de procedure_data antes del error: {procedure_data}")
            continue 

        final_key_for_search = procedure_data["titulo"].lower().strip() if procedure_data["titulo"] else os.path.splitext(filename)[0].lower()
        
        original_final_key = final_key_for_search
        counter = 1
        while final_key_for_search in tupa_procedures:
            final_key_for_search = f"{original_final_key}-{counter}"
            counter += 1
        
        tupa_procedures[final_key_for_search] = procedure_data
        
        if procedure_data["codigo"] and procedure_data["codigo"].lower().strip() not in tupa_procedures:
             tupa_procedures[procedure_data["codigo"].lower().strip()] = procedure_data
        
        logging.info(f"Cargado TUPA: \"{procedure_data['titulo'] if procedure_data['titulo'] else 'N/A'}\" (Clave principal: \"{final_key_for_search}\")")
        logging.debug(f"  Datos finales de '{filename}':")
        logging.debug(f"    Título: '{procedure_data['titulo']}'")
        logging.debug(f"    Código: '{procedure_data['codigo']}'")
        logging.debug(f"    Descripción (inicio): '{procedure_data['descripcion'][:100]}...'")
        logging.debug(f"    Requisitos (num): {len(procedure_data['requisitos'])}")
    
    logging.info(f"Carga de datos TUPA finalizada. Total de procedimientos cargados: {len(tupa_procedures)}")
    logging.info(f"Claves principales de procedimientos cargados: {list(tupa_procedures.keys())}")


load_tupa_data()

# --- FUNCIONES DE BÚSQUEDA Y LÓGICA DE RESPUESTA ---

# Palabras que suelen no aportar mucho a la búsqueda y pueden ser ignoradas
STOP_WORDS = set([
    "quiero", "saber", "como", "mi", "un", "una", "el", "la", "los", "las", "y", "o", "de", "del",
    "para", "con", "en", "por", "que", "es", "este", "esta", "estos", "estas", "a", "al", "del", "lo", "me", "del", "una",
    "sobre", "mas", "más", "hay", "informacion", "información", "respecto"
])

def clean_query_for_search(query):
    """
    Limpia la consulta del usuario, eliminando caracteres no alfanuméricos y stop words.
    """
    cleaned = re.sub(r'[^\w\s]', '', query).lower()
    words = [word for word in cleaned.split() if len(word) > 2 and word not in STOP_WORDS]
    return " ".join(words)

def find_matching_procedures(user_query):
    """
    Encuentra procedimientos TUPA que coinciden con la consulta del usuario
    y les asigna una puntuación de relevancia.
    """
    user_query_lower = user_query.lower()
    cleaned_query = clean_query_for_search(user_query_lower)
    query_words = cleaned_query.split()
    
    unique_procedures_seen = set()
    unique_procedures_list = []
    for proc_data in tupa_procedures.values():
        if id(proc_data) not in unique_procedures_seen:
            unique_procedures_seen.add(id(proc_data))
            unique_procedures_list.append(proc_data)

    exact_matches = []
    # Prioridad 1: Coincidencia exacta con título o código (sin stop words)
    for details in unique_procedures_list:
        if details.get("titulo") and cleaned_query == clean_query_for_search(details["titulo"]).strip():
            exact_matches.append(details)
        if details.get("codigo") and cleaned_query == clean_query_for_search(details["codigo"]).strip():
            exact_matches.append(details)
    
    if exact_matches:
        logging.debug(f"Coincidencia exacta limpia encontrada para '{cleaned_query}'")
        return exact_matches 

    if not query_words:
        return []

    scored_matches = []
    for details in unique_procedures_list:
        title_lower = details.get("titulo", "").lower().strip()
        description_lower = details.get("descripcion", "").lower().strip()

        score = 0
        
        # Aumentar bonos por palabras clave directas en título y descripción
        for word in query_words:
            if word in title_lower:
                score += 10 
            if word in description_lower:
                score += 4 

        # Bono por frase completa o subcadena significativa en el título (usando la query limpia)
        if cleaned_query in title_lower and len(cleaned_query) > 5:
            score += 20 
        # Bono si el título empieza con la consulta limpia
        if title_lower.startswith(cleaned_query) and len(cleaned_query) >= 3:
            score += 15 
        # Bono si todas las palabras de la consulta limpia están en el título
        if len(query_words) > 1 and all(word in title_lower for word in query_words):
            score += 25 
        elif len(query_words) > 1 and all(word in description_lower for word in query_words):
            score += 8 

        # --- Manejo específico para "EVALUACIÓN Y APROBACIÓN DE PROGRAMA DE RECONVERSIÓN" ---
        reconversion_keywords_exact = ["evaluacion y aprobacion del programa de reconversion", "evaluacion y aprobacion del programa de reconversion forestal", "evaluacion y aprobacion del programa de reconversion agraria"]
        reconversion_keywords_partial = ["evaluacion", "aprobacion", "programa", "reconversion", "forestal", "agrario"]
        
        is_query_reconversion_related = any(k in user_query_lower for k in reconversion_keywords_partial)

        if is_query_reconversion_related:
            if any(clean_query_for_search(k) in title_lower for k in reconversion_keywords_exact):
                score += 150 
            elif any(k in title_lower for k in reconversion_keywords_partial):
                score += 50 
            elif any(k in description_lower for k in reconversion_keywords_partial):
                score += 25 

        # --- Manejo específico para "LICENCIA DE EDIFICACIÓN" ---
        edificacion_keywords_exact = ["licencia de edificacion", "licencia de edificación modalidad c edificaciones de uso mixto con vivienda", "licencia de edificación modalidad d"]
        edificacion_keywords_partial = ["edificacion", "construccion", "obra", "licencia", "declaratoria de fabrica", "ampliacion", "remodelacion"]
        
        is_query_edificacion_related = any(k in user_query_lower for k in edificacion_keywords_partial)

        if is_query_edificacion_related:
            if any(clean_query_for_search(k) in title_lower for k in edificacion_keywords_exact):
                score += 150 
            elif any(k in title_lower for k in edificacion_keywords_partial):
                score += 60 
            elif any(k in description_lower for k in edificacion_keywords_partial):
                score += 30 


        # --- MEJORA CLAVE: Sinónimos para "LICENCIA DE CONDUCIR" ---
        license_keywords = ["licencia de conducir", "brevete", "pase de conducir"]
        is_query_license_related = any(k in user_query_lower for k in license_keywords)
        
        if is_query_license_related:
            if any(clean_query_for_search(k) in title_lower for k in license_keywords):
                score += 70 
            elif any(k in description_lower for k in license_keywords):
                score += 35
            if not any(k in title_lower for k in license_keywords) and not any(k in description_lower for k in license_keywords):
                score -= 150 

        # --- MEJORA CLAVE: Sinónimos para "NACIMIENTO" y "REGISTRO CIVIL" ---
        birth_keywords_exact_match = ["inscripcion de partidas", "partida de nacimiento", "registro de nacimiento", "registro civil"]
        birth_keywords_partial_match = ["nacimiento", "recien nacido", "inscribir", "registrar", "bebe", "hijo", "partida", "inscripcion de partida de nacimiento ordinaria"] 
        
        is_query_birth_related = any(k in user_query_lower for k in birth_keywords_partial_match)

        if is_query_birth_related:
            if any(clean_query_for_search(k) in title_lower for k in birth_keywords_exact_match):
                score += 40 
            if any(k in title_lower for k in birth_keywords_partial_match):
                score += 20 
            elif any(k in description_lower for k in birth_keywords_partial_match):
                score += 10 
            
            vehicle_keywords = ["vehiculo", "moto", "triciclo", "placa", "motorizado", "no motorizado"]
            if any(k in title_lower for k in vehicle_keywords) and is_query_birth_related:
                score -= 300 

        # Manejo de sinónimos y consultas relacionadas para "divorcio" y "separación"
        if "divorcio" in user_query_lower or "separarme" in user_query_lower:
            if "separacion convencional" in title_lower or "divorcio ulterior" in title_lower or "separacion de mutuo acuerdo" in title_lower:
                score += 10 
            elif "matrimonio" in title_lower or "familia" in title_lower:
                score += 2 
            
        if "constancia vehicular" in user_query_lower:
            if "vehicular" in title_lower and "constancia" in title_lower:
                score += 10 
        
        # --- Penalización general para vehículos si la consulta NO es vehicular ---
        is_query_vehicle_related = any(k in user_query_lower for k in ["vehiculo", "moto", "triciclo", "placa", "motorizado", "no motorizado", "licencia", "conducir"])
        if not is_query_vehicle_related:
            vehicle_keywords_general = ["vehiculo", "moto", "triciclo", "placa", "motorizado", "no motorizado"]
            if any(k in title_lower for k in vehicle_keywords_general):
                score -= 100 

        if score > 0: 
            scored_matches.append((score, details))
            logging.debug(f"  Procedimiento: '{details.get('titulo', 'N/A')}', Score: {score}")
            
    scored_matches.sort(key=lambda x: x[0], reverse=True)
    
    found_procedures = [proc[1] for proc in scored_matches]
    
    return found_procedures


# --- RUTAS DE LA API ---

@app.route('/tupa_titles', methods=['GET'])
def get_tupa_titles():
    """Retorna una lista de todos los títulos de procedimientos TUPA únicos."""
    unique_titles_set = set()
    for details in tupa_procedures.values():
        if details.get('titulo'):
            unique_titles_set.add(details['titulo'])
    
    titles = sorted(list(unique_titles_set))
    return jsonify({"titles": titles})

@app.route('/chat', methods=['POST'])
def chat():
    """
    Maneja las solicitudes de chat del usuario, buscando en los procedimientos TUPA
    y utilizando Gemini como fallback si no se encuentra información relevante localmente.
    """
    user_message = request.json.get('message', '').lower()
    if not user_message:
        return jsonify({"response": "No se recibió ningún mensaje.", "response_type": "text"}), 400

    logging.info(f"Mensaje del usuario recibido: {user_message}")
    
    # Añadir mensaje del usuario al historial de conversación
    add_to_conversation_log("user", user_message)

    # Obtenemos los posibles procedimientos con sus scores
    all_scored_procedures = []
    unique_procedures_list = []
    unique_procedures_seen_ids = set()
    for proc_data in tupa_procedures.values():
        if id(proc_data) not in unique_procedures_seen_ids:
            unique_procedures_seen_ids.add(id(proc_data))
            unique_procedures_list.append(proc_data)

    user_query_cleaned = clean_query_for_search(user_message) 
    query_words = user_query_cleaned.split()

    # Recalcula scores para todos los procedimientos con la query actual
    for details in unique_procedures_list:
        title_lower = details.get("titulo", "").lower().strip()
        description_lower = details.get("descripcion", "").lower().strip()
        score = 0
        
        # Aumentar bonos por palabras clave directas en título y descripción
        for word in query_words:
            if word in title_lower: score += 10 
            if word in description_lower: score += 4 
        
        # Bono por frase completa o subcadena significativa en el título (usando la query limpia)
        if user_query_cleaned in title_lower and len(user_query_cleaned) > 5: score += 20 
        # Bono si el título empieza con la consulta limpia
        if title_lower.startswith(user_query_cleaned) and len(user_query_cleaned) >= 3: score += 15 
        # Bono si todas las palabras de la consulta limpia están en el título
        if len(query_words) > 1 and all(word in title_lower for word in query_words): score += 25 
        elif len(query_words) > 1 and all(word in description_lower for word in query_words): score += 8

        # Specific scoring for "EVALUACIÓN Y APROBACIÓN DE PROGRAMA DE RECONVERSIÓN"
        reconversion_keywords_exact = ["evaluacion y aprobacion del programa de reconversion", "evaluacion y aprobacion del programa de reconversion forestal", "evaluacion y aprobacion del programa de reconversion agraria"]
        reconversion_keywords_partial = ["evaluacion", "aprobacion", "programa", "reconversion", "forestal", "agrario"]
        is_query_reconversion_related = any(k in user_message for k in reconversion_keywords_partial)

        if is_query_reconversion_related:
            if any(clean_query_for_search(k) in title_lower for k in reconversion_keywords_exact):
                score += 150 
            elif any(k in title_lower for k in reconversion_keywords_partial):
                score += 50 
            elif any(k in description_lower for k in reconversion_keywords_partial):
                score += 25 

        # Specific scoring for "LICENCIA DE EDIFICACIÓN"
        edificacion_keywords_exact = ["licencia de edificacion", "licencia de edificación modalidad c edificaciones de uso mixto con vivienda", "licencia de edificación modalidad d"]
        edificacion_keywords_partial = ["edificacion", "construccion", "obra", "licencia", "declaratoria de fabrica", "ampliacion", "remodelacion"]
        is_query_edificacion_related = any(k in user_message for k in edificacion_keywords_partial)

        if is_query_edificacion_related:
            if any(clean_query_for_search(k) in title_lower for k in edificacion_keywords_exact):
                score += 150 
            elif any(k in title_lower for k in edificacion_keywords_partial):
                score += 60 
            elif any(k in description_lower for k in edificacion_keywords_partial):
                score += 30 

        # License keywords for scoring
        license_keywords = ["licencia de conducir", "brevete", "pase de conducir"]
        is_query_license_related = any(k in user_message for k in license_keywords)
        if is_query_license_related:
            if any(clean_query_for_search(k) in title_lower for k in license_keywords): score += 70
            elif any(k in description_lower for k in license_keywords): score += 35
            if not any(k in title_lower for k in license_keywords) and not any(k in description_lower for k in license_keywords):
                score -= 150

        # Birth keywords for scoring (modificado para incluir inscripcion de partida de nacimiento ordinaria)
        birth_keywords_exact_match = ["inscripcion de partidas", "partida de nacimiento", "registro de nacimiento", "registro civil"]
        birth_keywords_partial_match = ["nacimiento", "recien nacido", "inscribir", "registrar", "bebe", "hijo", "partida", "inscripcion de partida de nacimiento ordinaria"] 
        is_query_birth_related = any(keyword in user_message for keyword in birth_keywords_partial_match)
        if is_query_birth_related:
            if any(clean_query_for_search(k) in title_lower for k in birth_keywords_exact_match): score += 40
            if any(k in title_lower for k in birth_keywords_partial_match): score += 20
            elif any(k in description_lower for k in birth_keywords_partial_match): score += 10
            vehicle_keywords = ["vehiculo", "moto", "triciclo", "placa", "motorizado", "no motorizado"]
            if any(k in title_lower for k in vehicle_keywords) and is_query_birth_related:
                score -= 300

        # Vehicle keywords for general search penalty
        is_query_vehicle_related = any(k in user_message for k in ["vehiculo", "moto", "triciclo", "placa", "motorizado", "no motorizado", "licencia", "conducir"])
        if not is_query_vehicle_related:
            vehicle_keywords_general = ["vehiculo", "moto", "triciclo", "placa", "motorizado", "no motorizado"]
            if any(k in title_lower for k in vehicle_keywords_general):
                score -= 100

        # Divorce keywords for scoring
        if "divorcio" in user_message or "separacion" in user_message or "separarme" in user_message or "divorciarme" in user_message:
            if "separacion convencional" in title_lower or "divorcio ulterior" in title_lower or "separacion de mutuo acuerdo" in title_lower:
                score += 10
            elif "matrimonio" in title_lower or "familia" in title_lower:
                score += 2
        
        if "constancia vehicular" in user_message:
            if "vehicular" in title_lower and "constancia" in title_lower:
                score += 10

        if score > 0:
            all_scored_procedures.append((score, details))
    all_scored_procedures.sort(key=lambda x: x[0], reverse=True)


    # --- Lógica para MANEJO DE SELECCIÓN DIRECTA DE SUGERENCIAS (al hacer clic en botón) ---
    for proc in unique_procedures_list: 
        if user_message.strip() == proc.get('titulo', '').lower().strip():
            logging.info(f"Coincidencia exacta con título TUPA para '{user_message}'. Mostrando detalles.")
            response_text = format_procedure_details(proc)
            add_to_conversation_log("model", response_text) 
            return jsonify({
                "response": response_text,
                "response_type": "text"
            })
    # --- FIN Lógica para MANEJO DE SELECCIÓN DIRECTA DE SUGERENCIAS ---


    # --- Lógica para manejo específico de "LICENCIA DE CONDUCIR" ---
    license_query_keywords = ["licencia de conducir", "brevete", "sacar brevete", "obtener licencia", "pase de conducir"]
    is_license_query = any(keyword in user_message for keyword in license_query_keywords)

    if is_license_query:
        license_tupa_found = None
        for score, proc in all_scored_procedures: 
            title_lower = proc.get('titulo', '').lower()
            if any(clean_query_for_search(k) in title_lower for k in license_keywords) and score > 0:
                license_tupa_found = proc
                break 
        
        if license_tupa_found:
            logging.info(f"Coincidencia directa para consulta de licencia: {license_tupa_found.get('titulo')}")
            response_text = format_procedure_details(license_tupa_found)
            add_to_conversation_log("model", response_text) 
            return jsonify({
                "response": response_text,
                "response_type": "text"
            })
        else:
            response_text = (
                "Estimado ciudadano, la **licencia de conducir (brevete)** no se tramita en la Municipalidad Provincial de Puno. "
                "Este procedimiento se gestiona a través del **Ministerio de Transportes y Comunicaciones (MTC)** o la **Dirección Regional de Transportes y Comunicaciones (DRTC)** de su región. "
                "Le recomiendo visitar sus sitios web oficiales o contactarlos directamente para obtener información precisa sobre los requisitos y pasos para sacar su licencia."
            )
            add_to_conversation_log("model", response_text) 
            return jsonify({"response": response_text, "response_type": "text"})


    # --- Lógica para manejo específico de "LICENCIA DE EDIFICACIÓN" ---
    edificacion_keywords_exact = ["licencia de edificacion", "licencia de edificación modalidad c edificaciones de uso mixto con vivienda", "licencia de edificación modalidad d"]
    edificacion_keywords_partial = ["edificacion", "construccion", "obra", "licencia", "declaratoria de fabrica", "ampliacion", "remodelacion"]
    is_query_edificacion_related = any(k in user_message for k in edificacion_keywords_partial)

    if is_query_edificacion_related:
        edificacion_tupa_found = None
        relevant_edificacion_suggestions = []
        for score, proc in all_scored_procedures:
            title_lower = proc.get('titulo', '').lower()
            if any(k in title_lower for k in edificacion_keywords_partial) and score > 0:
                if any(clean_query_for_search(k) in title_lower for k in edificacion_keywords_exact) and score >= 100:
                    edificacion_tupa_found = proc
                    break
                elif score >= 10: 
                    relevant_edificacion_suggestions.append(proc)
        
        if edificacion_tupa_found:
            logging.info(f"Coincidencia directa para consulta de edificación: {edificacion_tupa_found.get('titulo')}")
            response_text = format_procedure_details(edificacion_tupa_found)
            add_to_conversation_log("model", response_text) 
            return jsonify({
                "response": response_text,
                "response_type": "text"
            })
        else:
            if relevant_edificacion_suggestions:
                suggestions_list = []
                seen_titles = set()
                for proc in relevant_edificacion_suggestions:
                    if proc.get('titulo') and proc['titulo'].lower().strip() not in seen_titles:
                        suggestions_list.append(proc['titulo'])
                        seen_titles.add(proc['titulo'].lower().strip())
                    if len(suggestions_list) >= 5: 
                        break
                
                if suggestions_list:
                    response_message = "He encontrado varios procedimientos de edificación que podrían ser relevantes. ¿Te refieres a alguno de estos o quieres especificar más? Si hay más, puedo ayudarte a buscar."
                    add_to_conversation_log("model", response_message + " Opciones: " + ", ".join(suggestions_list)) 
                    return jsonify({
                        "response_type": "suggestions",
                        "message": response_message,
                        "suggestions": suggestions_list
                    })
            
            response_text = (
                "Para trámites de **Licencia de Edificación**, te sugiero consultar la fuente oficial de la Municipalidad Provincial de Puno, "
                "como la Gerencia de Desarrollo Urbano o su página web, ya que no tengo información detallada para ese procedimiento específico. "
                "¿Hay algún otro trámite municipal en el que pueda ayudarte?"
            )
            add_to_conversation_log("model", response_text) 
            return jsonify({"response": response_text, "response_type": "text"})


    # --- Lógica para manejo específico de "Registro de Nacimiento" ---
    birth_query_keywords = ["nacimiento", "recien nacido", "inscribir hijo", "registrar hijo", "partida de nacimiento", "bebe", "hijo", "inscripcion de partidas", "inscripcion de partida de nacimiento ordinaria", "inscripcion de partidas por mandato judicial"] 
    is_birth_query = any(keyword in user_message for keyword in birth_query_keywords)
    
    if is_birth_query:
        judicial_mandate_tupa = None
        relevant_birth_suggestions = []

        for score, proc in all_scored_procedures:
            title_lower = proc.get('titulo', '').lower()
            
            if "inscripcion de partidas por mandato judicial" in title_lower:
                judicial_mandate_tupa = proc
                
            if any(k in title_lower for k in ["nacimiento", "partida", "registro civil", "menor", "registro de partida de nacimiento"]) and \
               not any(vk in title_lower for vk in ["vehiculo", "moto", "triciclo", "placa"]) and score > 0:
                
                if score >= 1: 
                    relevant_birth_suggestions.append(proc)
        
        suggestions_list_for_birth = []
        seen_titles_for_birth = set()

        if judicial_mandate_tupa and judicial_mandate_tupa['titulo'].lower().strip() not in seen_titles_for_birth:
            suggestions_list_for_birth.append(judicial_mandate_tupa['titulo'])
            seen_titles_for_birth.add(judicial_mandate_tupa['titulo'].lower().strip())
        
        for proc in relevant_birth_suggestions:
            if proc.get('titulo') and proc['titulo'].lower().strip() not in seen_titles_for_birth:
                suggestions_list_for_birth.append(proc['titulo'])
                seen_titles_for_birth.add(proc['titulo'].lower().strip())
            if len(suggestions_list_for_birth) >= 5: 
                break
        
        response_text_prefix = (
            "Para la **inscripción de un recién nacido** y la obtención de su partida de nacimiento, "
            "este trámite se gestiona directamente en el **Registro Nacional de Identificación y Estado Civil (RENIEC)**, "
            "no en la Municipalidad Provincial de Puno. "
            "Por favor, diríjase a las oficinas de RENIEC o consulte su sitio web oficial para más detalles. "
        )

        if suggestions_list_for_birth:
            response_message = response_text_prefix + "\n\nSin embargo, he encontrado otros trámites relacionados que gestionamos en la municipalidad y que podrían ser de tu interés. ¿Te refieres a alguno de estos o quieres especificar más?"
            add_to_conversation_log("model", response_message + " Opciones: " + ", ".join(suggestions_list_for_birth)) 
            return jsonify({
                "response_type": "suggestions",
                "message": response_message,
                "suggestions": suggestions_list_for_birth
            })
        else:
            response_text = response_text_prefix + "\n¿Hay algún otro trámite municipal en el que pueda ayudarte?"
            add_to_conversation_log("model", response_text) 
            return jsonify({"response": response_text, "response_type": "text"})


    # --- Lógica de Manejo de "Divorcio/Separación" (se mantiene consistente) ---
    separation_tupa_keywords = ["separacion convencional", "divorcio ulterior", "separacion de mutuo acuerdo"]
    is_divorce_or_separation_query = any(k in user_message for k in ["divorcio", "separacion", "separarme", "divorciarme"])

    if is_divorce_or_separation_query:
        separation_tupa_found_in_db = None
        relevant_separation_suggestions = []

        for score, proc in all_scored_procedures:
            title_lower = proc.get('titulo', '').lower()
            if any(keyword in title_lower for keyword in separation_tupa_keywords) and score > 0:
                if (clean_query_for_search("separacion convencional") in title_lower or \
                    clean_query_for_search("divorcio ulterior") in title_lower) and score >= 10:
                    separation_tupa_found_in_db = proc
                if score > 0: # Collect all relevant suggestions
                    relevant_separation_suggestions.append(proc)

        if separation_tupa_found_in_db and len(clean_query_for_search(user_message).split()) > 2 and \
           (user_message.strip() == separation_tupa_found_in_db.get('titulo', '').lower().strip() or \
            "separacion convencional" in user_message and "separacion convencional" in separation_tupa_found_in_db.get('titulo', '').lower()):
             response_text = format_procedure_details(separation_tupa_found_in_db)
             add_to_conversation_log("model", response_text) 
             return jsonify({
                 "response": response_text,
                 "response_type": "text"
             })
        else: 
            suggestions_list = []
            seen_titles = set()

            for proc in relevant_separation_suggestions:
                if proc.get('titulo') and proc['titulo'].lower().strip() not in seen_titles:
                    suggestions_list.append(proc['titulo'])
                    seen_titles.add(proc['titulo'].lower().strip())
                if len(suggestions_list) >= 5:
                    break

            base_message = (
                "Estimado usuario, la Municipalidad Provincial de Puno gestiona trámites de **separación convencional** "
                "de mutuo acuerdo (sin hijos menores o mayores con incapacidad, y sin sociedad de gananciales por liquidar) "
                "o **divorcio ulterior** (después de una separación de hecho o legal). "
                "Sin embargo, los procesos de **divorcio o separación contenciosos (judiciales o notariales con conflictos)** "
                "NO se gestionan directamente en esta municipalidad. Para esos casos, le recomiendo consultar con un abogado "
                "especializado en derecho de familia o dirigirse a los juzgados correspondientes. "
            )

            if suggestions_list:
                response_message = base_message + "\n\nSi buscas información sobre los trámites que sí gestionamos, ¿te refieres a alguno de estos o quieres especificar más?"
                add_to_conversation_log("model", response_message + " Opciones: " + ", ".join(suggestions_list)) 
                return jsonify({
                    "response_type": "suggestions",
                    "message": response_message,
                    "suggestions": suggestions_list
                })
            else:
                response_text = base_message + "Si buscas información sobre la Separación Convencional y Divorcio Ulterior que se tramita aquí, por favor, indícalo."
                add_to_conversation_log("model", response_text) 
                return jsonify({"response": response_text, "response_type": "text"})


    # --- Lógica para cualquier otra consulta (General TUPA Search) ---
    # Define un umbral bajo para considerar una coincidencia como "relevante" para TUPA.
    # Si la mejor coincidencia es menor a este umbral, se considera una consulta no-TUPA.
    NO_TUPA_THRESHOLD = 3 

    if not all_scored_procedures or all_scored_procedures[0][0] < NO_TUPA_THRESHOLD:
        logging.info(f"Consulta detectada como no TUPA o muy débilmente relacionada: '{user_message}'. Score máximo: {all_scored_procedures[0][0] if all_scored_procedures else 'N/A'}.")
        response_text = (
            "Disculpa, mi función se limita a brindarte información sobre **procedimientos TUPA** de la Municipalidad Provincial de Puno. "
            "No puedo ayudarte con preguntas que no estén relacionadas con trámites municipales."
            "Por favor, intenta preguntar sobre un procedimiento específico."
        )
        add_to_conversation_log("model", response_text)
        return jsonify({"response": response_text, "response_type": "text"})

    # Si se llegó aquí, significa que hay procedimientos TUPA con al menos una coincidencia débil (score >= NO_TUPA_THRESHOLD).
    top_score = all_scored_procedures[0][0]
    first_proc = all_scored_procedures[0][1]

    logging.debug(f"Top score para '{user_message}' (general TUPA): {top_score}")

    STRONG_MATCH_SCORE_THRESHOLD = 50 
    MIN_SUGGESTION_SCORE = 5 
    
    is_query_general_and_multiple_matches = False
    if len(query_words) <= 3 or len(user_query_cleaned) < 8: 
        count_good_suggestions = sum(1 for score, proc in all_scored_procedures if score >= MIN_SUGGESTION_SCORE)
        if count_good_suggestions > 1: 
            is_query_general_and_multiple_matches = True
            logging.debug(f"  Consulta detectada como general y con múltiples buenos matches. Forzando sugerencias.")

    if top_score >= STRONG_MATCH_SCORE_THRESHOLD and not is_query_general_and_multiple_matches:
        response_text = format_procedure_details(first_proc)
        logging.info(f"Respuesta directa de TUPA (coincidencia fuerte general): {first_proc.get('titulo')}")
        add_to_conversation_log("model", response_text) 
        return jsonify({"response": response_text, "response_type": "text"})
    else:
        suggested_titles = []
        seen_titles = set()
        for score, proc in all_scored_procedures: 
            if score >= MIN_SUGGESTION_SCORE and proc.get('titulo') and proc['titulo'].lower().strip() not in seen_titles:
                suggested_titles.append(proc['titulo'])
                seen_titles.add(proc['titulo'].lower().strip())
            if len(suggested_titles) >= 5: 
                break
        
        if suggested_titles:
            response_message = "He encontrado varias opciones que podrían ser relevantes para tu búsqueda. ¿Te refieres a alguna de estas o quieres reformular tu pregunta para obtener resultados más específicos?"
            add_to_conversation_log("model", response_message + " Opciones: " + ", ".join(suggested_titles)) 
            return jsonify({
                "response_type": "suggestions",
                "message": response_message,
                "suggestions": suggested_titles
            })
        else:
            # Si se llega aquí, significa que hubo algunas coincidencias TUPA (score >= NO_TUPA_THRESHOLD),
            # pero no lo suficientemente fuertes para un match directo (no >= STRONG_MATCH_SCORE_THRESHOLD)
            # y tampoco se generaron suficientes "buenas" sugerencias (no >= MIN_SUGGESTION_SCORE).
            # En este caso, el bot seguirá indicando que no encontró algo específico, pero ya ha filtrado
            # las consultas que no son TUPA en absoluto.
            logging.info("Procedimientos TUPA encontrados, pero no suficientemente relevantes para sugerencias. No se recurre a Gemini.")
            response_text = (
                "Disculpa, no encontré un procedimiento TUPA que coincida exactamente con tu búsqueda. "
                "Por favor, intenta con otras palabras clave o sé más específico. "
                "Recuerda que solo puedo brindarte información sobre trámites municipales."
            )
            add_to_conversation_log("model", response_text)
            return jsonify({"response": response_text, "response_type": "text"})
    
    # El bloque de fallback a Gemini ha sido eliminado, ya que todas las rutas
    # deberían ser manejadas por la lógica de búsqueda TUPA local y los mensajes
    # de "fuera de dominio".

def format_procedure_details(matching_procedure):
    """
    Formatea los detalles de un procedimiento TUPA en un texto Markdown,
    resaltando títulos y secciones importantes en negrita.
    Asegura que la descripción muestre un mensaje si está vacía.
    """
    response_parts = []
    
    response_parts.append(f"El trámite que desea es este:")
    
    response_parts.append(f"**Procedimiento:** {matching_procedure.get('titulo', 'No disponible')}")
    response_parts.append(f"**Código:** {matching_procedure.get('codigo', 'No disponible')}")
    
    description = matching_procedure.get('descripcion', '').strip()
    if description:
        response_parts.append(f"**Descripción:** {description}")
    else:
        response_parts.append(f"**Descripción:** No se encontró una descripción detallada para este procedimiento.")
    
    response_parts.append("\n**Requisitos:**") 
    if matching_procedure['requisitos']:
        for req in matching_procedure['requisitos']:
            response_parts.append(f"- {req}")
    else:
        response_parts.append("- No se encontraron requisitos específicos en la base de datos para este procedimiento.")
    
    response_parts.append("\n**Canales de Atención:**")
    if matching_procedure['canales_atencion']:
        for canal in matching_procedure['canales_atencion']:
            response_parts.append(f"- {canal}")
    else:
        response_parts.append("- No se especificaron canales de atención.")

    response_parts.append("\n**Pago por Derecho de Tramitación:**")
    if matching_procedure['pago_derecho_tramitacion']['monto']:
        response_parts.append(f"- **Monto:** {matching_procedure['pago_derecho_tramitacion']['monto']}")
    if matching_procedure['pago_derecho_tramitacion']['modalidad']:
        response_parts.append(f"- **Modalidad de Pago:** {', '.join(matching_procedure['pago_derecho_tramitacion']['modalidad'])}")
    else:
        response_parts.append("- Información de pago no especificada.")

    response_parts.append(f"\n**Plazo:** {matching_procedure.get('plazo', 'No disponible')}")
    
    response_parts.append("\n**Sedes y Horarios de Atención:**")
    if matching_procedure['sedes_horarios']:
        for sede in matching_procedure['sedes_horarios']:
            response_parts.append(f"- {sede}")
    else:
        response_parts.append("- No se especificaron sedes u horarios.")

    response_parts.append(f"\n**Unidad donde se presenta la documentación:** {matching_procedure.get('unidad_presentacion', 'No disponible')}")
    response_parts.append(f"**Unidad responsable de aprobar:** {matching_procedure.get('unidad_aprobacion', 'No disponible')}")
    
    response_parts.append("\n**Consulta sobre el Servicio:**")
    phone_info = ""
    if matching_procedure['consulta_servicio']['telefono']:
        phone_info += f"- Teléfono: {matching_procedure['consulta_servicio']['telefono']}"
        if matching_procedure['consulta_servicio']['anexo']:
            phone_info += f" Anexo: {matching_procedure['consulta_servicio']['anexo']}"
    if phone_info:
        response_parts.append(phone_info)
    if matching_procedure['consulta_servicio']['correo']:
        response_parts.append(f"- Correo: {matching_procedure['consulta_servicio']['correo']}")
    
    if not phone_info and not matching_procedure['consulta_servicio']['correo']:
        response_parts.append("- Información de contacto no especificada.")

    return "\n".join(response_parts)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
