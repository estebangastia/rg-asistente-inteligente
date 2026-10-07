# Guion de la demostración en vivo (defensa oral)

Duración estimada: 6–7 minutos. Cubre lo que pidió el CAE: prototipo funcionando al
100 %, niveles de seguridad implementados y tecnología utilizada.

## Antes de la defensa (el día anterior)

1. Datos de demo limpios: en la nube, entrar como Gerencia → **Automatización** →
   **Reiniciar datos de demo** (dos clics: el botón pide confirmación). En local,
   `python seed_demo.py --reiniciar`. Las fechas quedan relativas al día del reinicio,
   así el contrato de López vence en 5 días y las obras aparecen demoradas.
2. Levantar el sistema (`iniciar_windows.bat` o `uvicorn main:app --port 8000`).
3. Abrir `http://localhost:8000/api/health` y confirmar:
   - `"estado": "operativo"`
   - `"motor_ia": "groq · openai/gpt-oss-120b"` (si se configuró la key)
   - 4 jobs activos
4. `pytest -q` → 59 tests en verde (sirve como evidencia si preguntan por calidad).
5. Tener abierta una segunda pestaña con `http://localhost:8000/docs` (Swagger).
6. Plan B: si no hay internet, el asistente responde igual con el motor de reglas y
   lo indica debajo de cada respuesta. Contarlo como decisión de diseño.

## 1. Tecnología (1 min)

- Swagger (`/docs`): API REST en **FastAPI**, endpoints agrupados por módulo.
- `/api/health`: motor de IA activo y los 4 jobs de **APScheduler**.
- Arquitectura: interfaz web → API Gateway FastAPI (JWT + roles) → módulos de negocio →
  PostgreSQL + motor RAG (LangChain + LLM) → jobs y SMTP.

## 2. Asistente conversacional (2 min) — usuario **Gerencia**

1. Ingresar con Gerencia (clic en el usuario de demo).
2. Panel ejecutivo: 5 contratos, 1 en mora, 2 obras, 3 clientes.
3. Asistente IA:
   - "¿Quién me debe plata?" (no dice "mora": demuestra comprensión del lenguaje)
   - "¿Qué obra está más atrasada y por qué?"
   - "¿A qué cliente tendría que llamar primero?"
   - Señalar la línea **"Respondido por: groq · openai/gpt-oss-120b"**.
4. Explicar RAG en una frase: *el sistema busca los datos en PostgreSQL según el rol del
   usuario y el modelo redacta la respuesta solo con esos datos; no se reentrena nada.*

## 3. Control de acceso por rol (1 min) — usuario **Jefe de obra**

1. Cerrar sesión, ingresar como Jefe de obra: el menú solo muestra Obras y Asistente.
2. Preguntar al asistente "¿Cuántos contratos están en mora?" → responde que su perfil
   no tiene acceso. **El modelo nunca recibe los datos de alquileres de este usuario.**

## 3b. Automatización (1–2 min) — usuario **Gerencia**

1. **Automatización** → mostrar el canal de email (Resend) y los horarios de los jobs.
2. "Ejecutar control de vencimientos" → detecta el contrato de López (vence en 5 días)
   y **llega el email al celular** en vivo.
3. "Ejecutar control de obras" → detecta las etapas demoradas y avisa.
4. La tabla de avisos muestra cada notificación con su estado (tabla NOTIFICACION).
   Es el objetivo específico 4 funcionando: detecta eventos y avisa sin intervención.

## 4. Seguridad (2–3 min) — usuario **Gerencia**

1. **Usuarios → Alta**: crear "Laura Benítez", rol Jefe de obra. Se genera una
   contraseña inicial aleatoria (en producción se envía por correo).
2. Cerrar sesión, ingresar como Laura: el sistema **obliga a cambiar la contraseña**.
   - Probar `hola123` → rechazada por la política de complejidad.
   - Probar una válida (ej. `Obra2026!Laura`) → ingresa.
3. Cerrar sesión e ingresar 5 veces con contraseña incorrecta →
   **"Cuenta bloqueada por 15 minutos"**. Aun con la clave correcta sigue bloqueada.
4. Volver como Gerencia → **Seguridad**:
   - Controles activos (bcrypt 12 rondas, JWT 8 h, bloqueo, 90 días, historial de 3).
   - **Log de auditoría**: aparecen el alta, los intentos fallidos, el bloqueo y el
     acceso denegado del Jefe de obra.
   - **Usuarios** → "Desbloquear" a Laura.
5. **Copias de seguridad**: "Generar copia ahora" y "Probar restauración de la última
   copia" → restaura en una base temporal aislada y compara registros: **OK**.
6. Mencionar la copia semanal en Amazon S3 (cifrado AES-256, acceso IAM) y la mensual
   en el servidor central, según la política descripta en el TFG.

## Preguntas probables y respuesta corta

- **¿Qué pasa si el modelo inventa datos?** El prompt le prohíbe responder fuera del
  contexto, la temperatura es baja (0,2) y solo recibe datos reales de la base.
- **¿Qué pasa si se cae la API del modelo?** Respuesta automática con el motor de reglas;
  queda registrado en el log y en la respuesta.
- **¿Por qué Groq en la demo y GPT-4o en el análisis de costos?** El motor es independiente
  del proveedor: se cambia desde `.env`. GPT-4o para producción; un plan gratuito para la
  demo. En producción conviene un plan pago también por privacidad de los datos.
- **¿Dónde están las contraseñas?** Solo el hash bcrypt en la tabla `usuarios`; nunca en
  el token ni en el log de auditoría.
