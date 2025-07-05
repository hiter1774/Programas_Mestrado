import tkinter as tk
from tkinter import ttk, messagebox
import serial
import serial.tools.list_ports
import threading
import time

# --- Configurações ---
DEFAULT_PORT = 'COM12' # Mude para a porta do seu ESP32!
BAUD_RATE = 115200

ser = None # Variável global para a porta serial
root = None # Variável global para a janela principal
log_text = None # Variável global para a área de log
motor_power_state = False # True = motor habilitado, False = motor desabilitado (para o botão único)
limit_switch_status_label = None # Label para o status do fim de curso
homed_status_label = None # REINTRODUZIDO: Label para o status do homing

# Calibração
calibration_step = 0 # Qual ponto de calibração estamos (0, 1, 2)
calibration_theoretical_inputs = [] # Para armazenar os objetos Entry para ângulos teóricos
calibration_measured_inputs = [] # Para armazenar os objetos Entry para ângulos medidos
calibration_data_for_esp32 = [] # Acumula os pares (teórico, medido) a serem enviados para o ESP32

# --- Funções de Comunicação Serial ---
def connect_serial():
    global ser
    port = port_combobox.get()
    if not port:
        messagebox.showerror("Erro", "Selecione uma porta serial.")
        return

    try:
        ser = serial.Serial(port, BAUD_RATE, timeout=0.1)
        status_label.config(text=f"Conectado em {port}", foreground="green")
        connect_button.config(state=tk.DISABLED)
        disconnect_button.config(state=tk.NORMAL)
        log_message(f"Conectado em {port}")
        
        serial_read_thread = threading.Thread(target=read_serial_continuously, daemon=True)
        serial_read_thread.start()

        update_gui_after_connect()
        
    except serial.SerialException as e:
        messagebox.showerror("Erro de Conexão", f"Não foi possível conectar à porta {port}:\n{e}")
        status_label.config(text="Desconectado", foreground="red")
        log_message(f"Erro ao conectar: {e}")

def disconnect_serial():
    global ser, motor_power_state
    if ser and ser.is_open:
        send_command("PARAR") # Tenta parar o motor
        send_command("DESABILITAR") # Desabilita o driver também
        motor_power_state = False
        update_power_button()
        time.sleep(0.05) # Pequeno delay para o comando ser enviado
        ser.close()
        ser = None
        status_label.config(text="Desconectado", foreground="red")
        connect_button.config(state=tk.NORMAL)
        disconnect_button.config(state=tk.DISABLED)
        disable_controls()
        log_message("Desconectado.")

def send_command(command):
    if ser and ser.is_open:
        try:
            ser.write(f"{command}\n".encode('utf-8'))
            log_message(f"Enviado: {command}")
        except serial.SerialException as e:
            messagebox.showerror("Erro de Envio", f"Erro ao enviar comando: {e}\nVerifique a conexão.")
            disconnect_serial()
    else:
        messagebox.showwarning("Aviso", "Não conectado à porta serial.")
        log_message("Não conectado, não pode enviar comando.")

def read_serial_continuously():
    """Lê continuamente da porta serial e atualiza o log."""
    while True:
        if ser and ser.is_open:
            try:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    log_message(f"Recebido da ESP32: {line}")
                    # Processa ACK messages e avisos
                    if line == "WARNING_LIMIT_SWITCH_ACTIVE" or line == "WARNING_LIMIT_SWITCH_HIT":
                        limit_switch_status_label.config(text="FIM DE CURSO ATIVO!", foreground="red", font=("Arial", 12, "bold"))
                    elif line == "ACK_LIMIT_SWITCH_RESET":
                         limit_switch_status_label.config(text="Fim de Curso: OK", foreground="green", font=("Arial", 10))
                    
                    if line == "ACK_PARADO" or line == "ACK_ANGULO_CONCLUIDO": 
                         limit_switch_status_label.config(text="Fim de Curso: OK", foreground="green", font=("Arial", 10)) # Reset visual
                         home_button.config(state=tk.NORMAL) # Habilita o botão de homing se o motor parou
                         enable_angle_controls_after_move() # Habilita os controles angulares após movimento
                    elif line == "ACK_HOMING_STARTED": # REINTRODUZIDO
                        homed_status_label.config(text="Homing: Em Andamento...", foreground="orange")
                        home_button.config(state=tk.DISABLED) # Desabilita o botão de homing durante o processo
                        disable_angle_controls() # Desabilita TODOS os controles de ângulo (incluindo direção) durante homing
                    elif line == "ACK_HOMING_CONCLUIDO": # REINTRODUZIDO
                        homed_status_label.config(text="Homing: CONCLUÍDO!", foreground="green", font=("Arial", 10, "bold"))
                        home_button.config(state=tk.NORMAL) # Habilita o botão novamente
                        enable_angle_controls() # Reabilita os controles de ângulo após homing
                    elif line == "ACK_NOT_HOMED": # REINTRODUZIDO
                        homed_status_label.config(text="Homing: NÃO CALIBRADO", foreground="red", font=("Arial", 10))
                        home_button.config(state=tk.NORMAL) # Habilita o botão home
                        enable_angle_controls() # HABILITA CONTROLES DE ÂNGULO MESMO SEM HOMING
                    elif "NACK_" in line: # Qualquer NACK de erro genérico
                        limit_switch_status_label.config(text="Fim de Curso: OK", foreground="green", font=("Arial", 10))
                        home_button.config(state=tk.NORMAL) # Habilita o botão home
                        homed_status_label.config(text="Homing: ERRO!", foreground="red") # Indica erro no homing
                        enable_angle_controls() # HABILITA CONTROLES DE ÂNGULO MESMO COM ERRO DE HOMING
                    elif "ACK_CALIBRATION_POINT" in line: # Processa ponto de calibração (GUI não usa mais este ACK para avançar)
                        pass 
                    elif line == "ACK_CALIBRATION_COMPLETE": # Recebido quando a ESP32 termina o cálculo
                        status_label_calibration.config(text="Calibração Concluída!", foreground="green", font=("Arial", 10, "bold"))
                        messagebox.showinfo("Calibração", "Calibração concluída! O fator de calibração foi ajustado no motor.")
                        cal_start_button.config(state=tk.NORMAL) # Reabilita iniciar nova calibração
                        cal_submit_button.config(state=tk.DISABLED) # Desabilita o botão Calcular/Enviar
                        cal_move_button.config(state=tk.DISABLED) # Desabilita mover durante o movimento
                        cal_submit_current_point_button.config(state=tk.DISABLED) # Desabilita o botão de registrar ponto
                        enable_angle_controls() # Reabilita os controles de ângulo se o motor está habilitado
                    elif line == "NACK_CALIBRATION_FACTOR_ZERO": # Erro de fator zero na calibração
                        status_label_calibration.config(text="Calibração falhou: Fator Zero!", foreground="red", font=("Arial", 10, "bold"))
                        messagebox.showerror("Erro de Calibração", "Fator de calibração resultou em zero. Refaça a calibração com medições mais variadas.")
                        cal_start_button.config(state=tk.NORMAL)
                        cal_submit_button.config(state=tk.DISABLED)
                        cal_submit_current_point_button.config(state=tk.DISABLED)
                        enable_angle_controls()
                    elif line == "ACK_CALIBRATION_RESET": # Calibração zerada
                        status_label_calibration.config(text="Calibração Zerada!", foreground="red", font=("Arial", 10, "bold"))
                        messagebox.showinfo("Calibração", "A calibração foi zerada para os valores padrão.")
                        cal_start_button.config(state=tk.NORMAL)
                        cal_submit_button.config(state=tk.DISABLED)
                        cal_submit_current_point_button.config(state=tk.DISABLED)
                        enable_angle_controls() # Habilita controles de ângulo
            except serial.SerialException as e:
                log_message(f"Erro de leitura serial: {e}")
                disconnect_serial()
                break
            except Exception as e:
                log_message(f"Erro inesperado na leitura serial: {e}")
        time.sleep(0.01)

def log_message(message):
    """Adiciona uma mensagem ao Text widget de log."""
    if log_text:
        log_text.insert(tk.END, message + "\n")
        log_text.see(tk.END)

# --- Funções de Controle do Motor ---

# Função para alternar o estado do motor (Habilitar/Desabilitar)
def toggle_motor_power():
    global motor_power_state
    if motor_power_state: # Se está ligado, vai desligar
        send_command("DESABILITAR")
    else: # Se está desligado, vai ligar
        send_command("HABILITAR")
    motor_power_state = not motor_power_state # Inverte o estado
    update_power_button() # Atualiza o texto do botão

# Função para atualizar o texto do botão de power
def update_power_button():
    if motor_power_state:
        motor_power_button.config(text="DESABILITAR MOTOR", style="Red.TButton")
        enable_angle_controls() # HABILITA OS CONTROLES QUANDO O MOTOR É HABILITADO
    else:
        motor_power_button.config(text="HABILITAR MOTOR", style="Green.TButton")
        disable_angle_controls() # Desabilita TODOS os controles de ângulo se o driver está OFF

def stop_motor(): # Apenas envia o comando PARAR
    send_command("PARAR")

def set_direction_forward():
    send_command("DIR FRENTE")

def set_direction_reverse():
    send_command("DIR RE")

# Função para mover por um ângulo inserido (AGORA COM FREQUÊNCIA AJUSTÁVEL)
def move_by_entered_angle():
    try:
        degrees = float(angle_entry.get())
        frequency_hz = int(angle_frequency_slider.get()) # Pega a frequência do slider

        if degrees < 0 or degrees > 360:
            messagebox.showwarning("Aviso", "O ângulo deve estar entre 0 e 360 graus.")
            return
        
        if not motor_power_state:
             messagebox.showwarning("Aviso", "Habilite o motor primeiro!")
             return
        
        # Formato do comando: "MOVER ANGULO <graus> <frequencia_hz>"
        send_command(f"MOVER ANGULO {degrees} {frequency_hz}")
        log_message(f"Comando: MOVER ANGULO {degrees} {frequency_hz} enviado.")
        
    except ValueError:
        messagebox.showerror("Erro", "Por favor, insira um número válido para o ângulo ou a frequência.")

# REINTRODUZIDO: Função go_home() (Homing agora é opcional e chamado por este botão)
def go_home():
    if not motor_power_state:
        messagebox.showwarning("Aviso", "Habilite o motor primeiro!")
        return
    # Desabilita controles de movimento durante o homing
    disable_angle_controls() 
    send_command("HOME")
    log_message("Comando: HOME enviado.")


def start_calibration_sequence(): # Inicia a sequência de calibração
    global calibration_step, calibration_theoretical_inputs, calibration_measured_inputs, calibration_data_for_esp32
    if not motor_power_state:
        messagebox.showwarning("Aviso", "Habilite o motor primeiro para iniciar a calibração.")
        return

    # A verificação de motor parado antes da calibração é feita no firmware
    
    calibration_step = 0
    calibration_theoretical_inputs = [] # Limpa antes de preencher
    calibration_measured_inputs = [] # Limpa antes de preencher
    calibration_data_for_esp32 = [] # Zera os dados a serem enviados

    # Limpa e cria campos de entrada para as medições
    for widget in calibration_entries_frame.winfo_children():
        widget.destroy()

    ttk.Label(calibration_entries_frame, text="Ponto").grid(row=0, column=0, padx=5, pady=5)
    ttk.Label(calibration_entries_frame, text="Teórico (°)").grid(row=0, column=1, padx=5, pady=5)
    ttk.Label(calibration_entries_frame, text="Medido (°)").grid(row=0, column=2, padx=5, pady=5)
    
    for i in range(3): # Cria 3 pares de campos de entrada
        ttk.Label(calibration_entries_frame, text=f"Ponto {i+1}").grid(row=i+1, column=0, padx=5, pady=2, sticky="w")
        
        entry_theoretical = ttk.Entry(calibration_entries_frame, width=8)
        entry_theoretical.grid(row=i+1, column=1, padx=5, pady=2, sticky="ew")
        entry_theoretical.insert(0, str((i+1)*90.0)) # Sugestão de valores (90, 180, 270)
        calibration_theoretical_inputs.append(entry_theoretical)

        entry_measured = ttk.Entry(calibration_entries_frame, width=8)
        entry_measured.grid(row=i+1, column=2, padx=5, pady=2, sticky="ew")
        calibration_measured_inputs.append(entry_measured)
        # Inicialmente desabilita todos os campos medidos
        calibration_measured_inputs[i].config(state=tk.DISABLED) 

    # Configura o estado inicial dos botões da calibração
    status_label_calibration.config(text=f"Pronto para Ponto 1: Insira Teórico e MOVA.", foreground="blue")
    cal_move_button.config(text=f"MOVER PARA PONTO 1", state=tk.NORMAL) # Habilita o primeiro mover
    cal_submit_button.config(text="CALCULAR CALIBRACAO", state=tk.DISABLED) # Desabilitado até 3 pontos serem enviados
    cal_submit_current_point_button.config(text="REGISTRAR MEDIÇÃO DO PONTO ATUAL", state=tk.DISABLED) # Habilitado após mover
    disable_angle_controls() # Desabilita controles normais durante calibração
    home_button.config(state=tk.DISABLED) # Desabilita home durante calibração
    cal_start_button.config(state=tk.DISABLED) # Desabilita iniciar nova calibração
    cal_disable_button.config(state=tk.NORMAL) # Habilita o botão de desabilitar calibração
    
    log_message("Iniciando Calibração. Preencha o ângulo teórico para o Ponto 1 e clique MOVER.")

def disable_calibration_sequence(): # Função para desabilitar a calibração
    global calibration_step
    calibration_step = 0 # Reseta o passo da calibração
    status_label_calibration.config(text="Calibração Desabilitada.", foreground="red")
    cal_move_button.config(state=tk.DISABLED)
    cal_submit_button.config(state=tk.DISABLED)
    cal_submit_current_point_button.config(state=tk.DISABLED)
    cal_start_button.config(state=tk.NORMAL) # Reabilita iniciar calibração
    cal_disable_button.config(state=tk.DISABLED) # Desabilita o próprio botão de desabilitar
    enable_angle_controls_after_move() # Reabilita controles de ângulo conforme o estado atual
    home_button.config(state=tk.NORMAL) # Reabilita home
    log_message("Calibração desabilitada pelo usuário.")

def reset_calibration_gui_and_send_command(): # Função para zerar a calibração
    response = messagebox.askyesno("Confirmar Reset", "Tem certeza que deseja zerar a calibração do motor? Isso redefinirá o fator para 1.0 e o motor para 'Não Calibrado'.")
    if response:
        send_command("RESET_CALIB")
        log_message("Comando: RESET_CALIB enviado.")
        # A GUI será atualizada pelas mensagens de ACK do ESP32

def submit_current_calibration_point(): # NOVO: Envia UM par (teórico, medido) para o ESP32 (apenas para registro na GUI)
    global calibration_step, calibration_data_for_esp32
    
    if calibration_step < 3: # Garante que estamos dentro dos 3 pontos
        try:
            theoretical_val = float(calibration_theoretical_inputs[calibration_step].get()) # Pega do campo correto
            measured_val = float(calibration_measured_inputs[calibration_step].get()) # Pega do campo correto

            if not (0 <= theoretical_val <= 360) or not (0 <= measured_val <= 360):
                messagebox.showerror("Erro de Calibração", f"Valores do Ponto {calibration_step+1} fora do range (0-360).")
                return
            
            # Acumula o par na lista local da GUI
            calibration_data_for_esp32.append( (theoretical_val, measured_val) ) 

            log_message(f"Ponto {calibration_step+1} registrado: Teórico={theoretical_val}°, Medido={measured_val}°")
            
            # Desabilita os campos do ponto atual após registrar
            calibration_theoretical_inputs[calibration_step].config(state=tk.DISABLED)
            calibration_measured_inputs[calibration_step].config(state=tk.DISABLED)
            cal_submit_current_point_button.config(state=tk.DISABLED) # Desabilita o botão de enviar este ponto

            calibration_step += 1 # Avança para o próximo passo/ponto

            if calibration_step < 3: # Se ainda faltam pontos a mover/registrar
                cal_move_button.config(text=f"MOVER PARA PONTO {calibration_step+1}", state=tk.NORMAL)
                status_label_calibration.config(text=f"Pronto para Ponto {calibration_step+1}: Insira Teórico e MOVA.", foreground="blue")
            else: # Se os 3 pontos foram registrados na GUI
                cal_move_button.config(text="TODOS OS PONTOS MOVIDOS", state=tk.DISABLED)
                cal_submit_button.config(text="CALCULAR CALIBRACAO", state=tk.NORMAL) # Habilita o botão FINAL de CALCULAR CALIBRACAO
                status_label_calibration.config(text="Todos os pontos coletados. Pressione 'CALCULAR CALIBRACAO'.", foreground="green")

        except ValueError:
            messagebox.showerror("Erro", "Por favor, insira números válidos para a medição do ponto atual.")
        except Exception as e:
            messagebox.showerror("Erro Inesperado", f"Ocorreu um erro ao registrar ponto de calibração: {e}")
    else:
        messagebox.showwarning("Calibração", "Todos os pontos já foram registrados na GUI.")


def submit_all_calibration_data_to_esp32(): # Envia TODOS os 3 pares para o ESP32 (chamado por CALCULAR CALIBRACAO)
    if len(calibration_data_for_esp32) != 3:
        messagebox.showerror("Erro de Calibração", "Dados insuficientes! Colete 3 pontos antes de calcular.")
        return

    calibration_data_string = "CALIBRAR "
    for i, (theoretical, measured) in enumerate(calibration_data_for_esp32):
        # Formato: teorico,medido;
        calibration_data_string += f"{theoretical},{measured}"
        if i < 2: # Adiciona o ponto e vírgula entre os pares, mas não depois do último
            calibration_data_string += ";"
    
    send_command(calibration_data_string)
    log_message(f"Comando de CALIBRACAO com 3 pontos enviado para o ESP32: {calibration_data_string}")
    
    cal_submit_button.config(state=tk.DISABLED) # Desabilita o botão de calcular/enviar
    status_label_calibration.config(text="Calculando calibração no motor...", foreground="blue")


def trigger_calibration_move(): # Move o motor para o ponto teórico do passo atual
    global calibration_step
    
    if calibration_step < 3: # Limita a 3 movimentos para os 3 pontos
        try:
            angle_to_move = float(calibration_theoretical_inputs[calibration_step].get())
            
            if not (0 <= angle_to_move <= 360):
                messagebox.showwarning("Aviso", "O ângulo teórico inserido deve estar entre 0 e 360 graus.")
                return
            
            # Habilita o campo de medição para o ponto atual
            calibration_measured_inputs[calibration_step].config(state=tk.NORMAL)
            calibration_measured_inputs[calibration_step].focus_set() # Coloca foco no campo
            
            # Envia o comando para mover o motor para o ângulo teórico, com frequência padrão
            send_command(f"MOVER ANGULO {angle_to_move} 50") # Frequência padrão 50Hz para calibração
            status_label_calibration.config(text=f"Movendo para {angle_to_move}°. Meça e insira o valor real.", foreground="blue")
            cal_move_button.config(state=tk.DISABLED) # Desabilita mover durante o movimento
            # O botão de registrar medição será habilitado após o ACK do ESP32 (ACK_ANGULO_CONCLUIDO)
            
        except ValueError:
            messagebox.showerror("Erro", "Por favor, insira um número válido para o ângulo teórico.")
    else:
        messagebox.showinfo("Calibração", "Todos os pontos já foram movidos. Pressione 'CALCULAR CALIBRACAO'.")


# --- Funções da GUI ---
def populate_ports():
    ports = serial.tools.list_ports.comports()
    port_names = [port.device for port in ports]
    port_combobox['values'] = port_names
    if DEFAULT_PORT in port_names:
        port_combobox.set(DEFAULT_PORT)
    elif port_names:
        port_combobox.set(port_names[0])

def disable_controls():
    motor_power_button.config(state=tk.DISABLED)
    stop_button.config(state=tk.DISABLED)
    dir_fwd_button.config(state=tk.DISABLED)
    dir_rev_button.config(state=tk.DISABLED)
    angle_entry.config(state=tk.DISABLED)
    move_angle_button.config(state=tk.DISABLED)
    angle_frequency_slider.config(state=tk.DISABLED)
    home_button.config(state=tk.DISABLED) # REINTRODUZIDO
    
    # Calibração
    cal_start_button.config(state=tk.DISABLED)
    cal_move_button.config(state=tk.DISABLED)
    cal_submit_button.config(state=tk.DISABLED)
    cal_submit_current_point_button.config(state=tk.DISABLED) 
    cal_disable_button.config(state=tk.DISABLED) 
    cal_reset_button.config(state=tk.DISABLED)
    
    # Desabilita campos de entrada da calibração se existirem
    for entry in calibration_theoretical_inputs + calibration_measured_inputs:
        entry.config(state=tk.DISABLED)

def enable_controls():
    motor_power_button.config(state=tk.NORMAL)
    stop_button.config(state=tk.NORMAL)
    update_power_button() 
    home_button.config(state=tk.NORMAL) # REINTRODUZIDO
    
    cal_start_button.config(state=tk.NORMAL) # Habilita iniciar calibração
    cal_disable_button.config(state=tk.DISABLED) # Inicia desabilitado
    cal_reset_button.config(state=tk.NORMAL)

    # Nao habilita os campos de calibração aqui, apenas quando a sequência inicia

def disable_angle_controls():
    # Desabilita TODOS os controles de movimento/ângulo, incluindo os de direção
    dir_fwd_button.config(state=tk.DISABLED)
    dir_rev_button.config(state=tk.DISABLED)
    angle_entry.config(state=tk.DISABLED)
    move_angle_button.config(state=tk.DISABLED)
    angle_frequency_slider.config(state=tk.DISABLED)

def enable_angle_controls():
    # Habilita os controles de movimento/ângulo.
    # Esta função é chamada quando o motor está habilitado.
    if motor_power_state: # Apenas se o motor estiver ligado
        dir_fwd_button.config(state=tk.NORMAL)
        dir_rev_button.config(state=tk.NORMAL)
        angle_entry.config(state=tk.NORMAL)
        move_angle_button.config(state=tk.NORMAL)
        angle_frequency_slider.config(state=tk.NORMAL)

def enable_angle_controls_after_move(): # Chamado após movimento normal parar (ACK_ANGULO_CONCLUIDO ou ACK_PARADO)
    # Lógica para reabilitar botões da calibração após um movimento de teste
    if status_label_calibration.cget("text").startswith("Movendo para"): # Se acabou de mover um ponto de calibração
        cal_submit_current_point_button.config(state=tk.NORMAL) # Habilita o botão de registrar medição
    elif status_label_calibration.cget("text").startswith("Pronto para ponto"): # Se está pronto para um novo ponto (mas não moveu ainda)
        cal_move_button.config(state=tk.NORMAL) # Habilita o mover para o próximo ponto
    elif status_label_calibration.cget("text") == "Todos os pontos coletados. Pressione para calibrar.":
        cal_submit_button.config(state=tk.NORMAL) # Habilita o botão final de calcular calibração

    # Se não está em calibração (ou a calibração não precisa de mais movimentos), reabilita os controles normais.
    elif motor_power_state: 
        enable_angle_controls()
    else:
        disable_angle_controls()


def update_gui_after_connect():
    enable_controls()
    # Atualiza o label da frequência inicial do slider
    set_angle_frequency_from_slider(angle_frequency_label)
    # Motor não está "homed" por padrão na conexão
    homed_status_label.config(text="Homing: NÃO CALIBRADO", foreground="red") # REINTRODUZIDO
    status_label_calibration.config(text="Não Calibrado. Inicie a calibração.", foreground="red") # Reset status calibração
    # Garante que os controles de ângulo estão habilitados se o motor já está ligado (novo requisito)
    if motor_power_state:
        enable_angle_controls()
    else:
        disable_angle_controls()


def set_angle_frequency_from_slider(label_widget):
    frequency_hz = int(angle_frequency_slider.get())
    label_widget.config(text=f"Frequência (Hz): {frequency_hz} Hz")

# --- Configuração da GUI ---
def create_gui():
    # Declara todas as variáveis globais de widgets no início de create_gui()
    # Isso garante que elas sejam acessíveis de outras funções após a criação.
    global root, log_text, port_combobox, connect_button, disconnect_button, status_label
    global motor_power_button, stop_button, dir_fwd_button, dir_rev_button
    global angle_entry, move_angle_button, angle_frequency_slider, angle_frequency_label
    global limit_switch_status_label, homed_status_label, home_button # REINTRODUZIDO: homed_status_label e home_button
    global cal_start_button, cal_move_button, cal_submit_button, status_label_calibration, calibration_entries_frame, cal_disable_button, cal_reset_button, cal_submit_current_point_button

    root = tk.Tk()
    root.title("Controle de Motor de Passo ESP32")
    root.geometry("1200x700") # Aumenta a largura e altura
    root.resizable(True, True) # Permite redimensionamento da janela

    style = ttk.Style()
    style.configure("TButton", font=("Arial", 10), padding=5)
    style.configure("TLabel", font=("Arial", 10))
    style.configure("TScale", troughcolor="#ccc", sliderrelief="flat") 
    style.configure("TRadiobutton", font=("Arial", 10)) 
    style.configure("Red.TButton", background="#f00", foreground="white", font=("Arial", 10, "bold"))
    style.map("Red.TButton", background=[('active', '#c00')])
    style.configure("Green.TButton", background="#0c0", foreground="white", font=("Arial", 10, "bold"))
    style.map("Green.TButton", background=[('active', '#a00')]) # Altera a cor de clique para verde escuro


    # --- FRAME PRINCIPAL PARA CONTEÚDO HORIZONTAL ---
    main_content_frame = ttk.Frame(root, padding=10)
    main_content_frame.pack(fill="both", expand=True)
    main_content_frame.grid_columnconfigure(0, weight=1) 
    main_content_frame.grid_columnconfigure(1, weight=1) 
    main_content_frame.grid_rowconfigure(0, weight=1) # Permite que a única linha se expanda

    # --- Coluna 0: Controles do Motor (Conexão, Geral, Ângulo) ---
    col0_frame = ttk.Frame(main_content_frame, padding=5)
    col0_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
    col0_frame.grid_rowconfigure(0, weight=0) 
    col0_frame.grid_rowconfigure(1, weight=0) 
    col0_frame.grid_rowconfigure(2, weight=1) 

    # Frame para Conexão Serial
    conn_frame = ttk.LabelFrame(col0_frame, text="Conexão Serial", padding=10)
    conn_frame.grid(row=0, column=0, sticky="ew", pady=5) 

    ttk.Label(conn_frame, text="Porta COM:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
    port_combobox = ttk.Combobox(conn_frame, width=15)
    port_combobox.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

    connect_button = ttk.Button(conn_frame, text="Conectar", command=connect_serial)
    connect_button.grid(row=0, column=2, padx=5, pady=5)

    disconnect_button = ttk.Button(conn_frame, text="Desconectar", command=disconnect_serial, state=tk.DISABLED)
    disconnect_button.grid(row=0, column=3, padx=5, pady=5)

    status_label = ttk.Label(conn_frame, text="Desconectado", foreground="red")
    status_label.grid(row=1, column=0, columnspan=4, pady=5)

    populate_ports()

    # Frame para Status e Controle Geral
    general_control_frame = ttk.LabelFrame(col0_frame, text="Status e Controle Geral", padding=10)
    general_control_frame.grid(row=1, column=0, sticky="ew", pady=5) 

    limit_switch_status_label = ttk.Label(general_control_frame, text="Fim de Curso: OK", foreground="green", font=("Arial", 10))
    limit_switch_status_label.grid(row=0, column=0, columnspan=2, padx=5, pady=5, sticky="w") 

    homed_status_label = ttk.Label(general_control_frame, text="Homing: NÃO CALIBRADO", foreground="red", font=("Arial", 10)) # REINTRODUZIDO
    homed_status_label.grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky="w") 

    motor_power_button = ttk.Button(general_control_frame, text="HABILITAR MOTOR", command=toggle_motor_power, style="Green.TButton")
    motor_power_button.grid(row=0, column=3, padx=5, pady=5, sticky="ew")

    stop_button = ttk.Button(general_control_frame, text="PARAR MOVIMENTO", command=stop_motor, style="TButton")
    stop_button.grid(row=2, column=0, columnspan=4, padx=5, pady=5, sticky="ew")

    dir_label = ttk.Label(general_control_frame, text="Direção:")
    dir_label.grid(row=3, column=0, padx=5, pady=5, sticky="w")
    dir_fwd_button = ttk.Button(general_control_frame, text="FRENTE", command=set_direction_forward, style="TButton")
    dir_fwd_button.grid(row=3, column=1, padx=5, pady=5, sticky="ew")
    dir_rev_button = ttk.Button(general_control_frame, text="REVERSO", command=set_direction_reverse, style="TButton")
    dir_rev_button.grid(row=3, column=2, padx=5, pady=5, sticky="ew")

    home_button = ttk.Button(general_control_frame, text="IR PARA PONTO ZERO", command=go_home, style="TButton") # REINTRODUZIDO
    home_button.grid(row=1, column=3, padx=5, pady=5, sticky="ew") 

    # Frame para Controle por Ângulo
    angle_control_frame = ttk.LabelFrame(col0_frame, text="Controle por Ângulo (0-360 Graus)", padding=10)
    angle_control_frame.grid(row=2, column=0, sticky="nsew", pady=5) 
    col0_frame.grid_rowconfigure(2, weight=1) 

    ttk.Label(angle_control_frame, text="Ângulo (graus):").grid(row=0, column=0, padx=5, pady=5, sticky="w")
    angle_entry = ttk.Entry(angle_control_frame, width=10)
    angle_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
    angle_entry.insert(0, "90.0") 

    ttk.Label(angle_control_frame, text="Frequência (Hz):").grid(row=1, column=0, padx=5, pady=5, sticky="w")
    angle_frequency_slider = ttk.Scale(angle_control_frame, from_=1, to=200, orient="horizontal", command=lambda val: set_angle_frequency_from_slider(angle_frequency_label))
    angle_frequency_slider.set(50) 
    angle_frequency_slider.grid(row=2, column=0, columnspan=4, padx=5, pady=5, sticky="ew")

    angle_frequency_label = ttk.Label(angle_control_frame, text="Frequência (Hz): 50 Hz") 
    angle_frequency_label.grid(row=3, column=0, columnspan=4, padx=5, pady=5, sticky="w")
    
    move_angle_button = ttk.Button(angle_control_frame, text="MOVER ÂNGULO", command=move_by_entered_angle, style="TButton")
    move_angle_button.grid(row=0, column=2, columnspan=2, padx=5, pady=5, sticky="ew")

    # --- Coluna 1: Calibração e Log ---
    col1_frame = ttk.Frame(main_content_frame, padding=5)
    col1_frame.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
    col1_frame.grid_rowconfigure(0, weight=0) # Calibração (não expande)
    col1_frame.grid_rowconfigure(1, weight=1) # Log (expansível)

    # Frame para Calibração
    calibration_frame = ttk.LabelFrame(col1_frame, text="Calibração do Motor", padding=10)
    calibration_frame.grid(row=0, column=0, sticky="ew", pady=5) 

    status_label_calibration = ttk.Label(calibration_frame, text="Não Calibrado. Inicie a calibração.", foreground="red")
    status_label_calibration.pack(pady=5, fill="x") 

    cal_start_button = ttk.Button(calibration_frame, text="INICIAR CALIBRAÇÃO", command=start_calibration_sequence)
    cal_start_button.pack(pady=5, fill="x")

    calibration_entries_frame = ttk.Frame(calibration_frame) 
    calibration_entries_frame.pack(pady=5)

    cal_move_button = ttk.Button(calibration_frame, text="MOVER PARA PONTO DE MEDIÇÃO", command=trigger_calibration_move, state=tk.DISABLED)
    cal_move_button.pack(pady=5, fill="x")

    cal_submit_current_point_button = ttk.Button(calibration_frame, text="REGISTRAR MEDIÇÃO DO PONTO ATUAL", command=submit_current_calibration_point, state=tk.DISABLED)
    cal_submit_current_point_button.pack(pady=5, fill="x")

    cal_submit_button = ttk.Button(calibration_frame, text="CALCULAR CALIBRACAO", command=submit_all_calibration_data_to_esp32, state=tk.DISABLED)
    cal_submit_button.pack(pady=5, fill="x")

    cal_disable_button = ttk.Button(calibration_frame, text="DESABILITAR CALIBRAÇÃO", command=disable_calibration_sequence, state=tk.DISABLED)
    cal_disable_button.pack(pady=5, fill="x")

    cal_reset_button = ttk.Button(calibration_frame, text="ZERAR CALIBRAÇÃO", command=reset_calibration_gui_and_send_command)
    cal_reset_button.pack(pady=5, fill="x")

    # Frame de Log
    log_frame = ttk.LabelFrame(col1_frame, text="Log de Comunicação", padding=10)
    log_frame.grid(row=1, column=0, sticky="nsew", pady=5) 
    col1_frame.grid_rowconfigure(1, weight=1) 

    log_text = tk.Text(log_frame, wrap="word", height=15) 
    log_text.pack(fill="both", expand=True)
    log_scrollbar = ttk.Scrollbar(log_frame, command=log_text.yview)
    log_scrollbar.pack(side="right", fill="y")
    log_text.config(yscrollcommand=log_scrollbar.set)

    disable_controls() 

    root.mainloop()

if __name__ == "__main__":
    create_gui()