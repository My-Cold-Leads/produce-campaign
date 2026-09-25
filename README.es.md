# Pipeline de Producción de Campañas de Cold Email

Este es el pipeline exacto de producción de campañas que usamos en nuestra agencia de cold email para llevar a un cliente de cero a campaña lanzada. Es un skill de Claude Code - lo instalas, escribes `/produce-campaign`, y Claude te guía paso a paso.

## Por qué lo compartimos

Hay demasiados consejos vagos sobre cold email y muy pocos playbooks reales. "Personaliza tus emails" no te dice cómo hacerlo a escala sin destrozar la reputación de tu dominio o enviar basura.

Construimos este pipeline ejecutando campañas reales para clientes reales. Cada control de calidad existe porque algo se rompió sin él. Cada paso de validación existe porque una vez nos lo saltamos y pagamos el precio - datos incorrectos enviados a leads, dominios quemados, campañas eliminadas por filtros de spam.

Lo compartimos porque creemos que la industria mejora cuando la gente deja de adivinar y empieza a seguir un proceso. Esperamos que te ahorre el mismo dolor que nos ahorró a nosotros.

## Para quién es esto

**Nunca has lanzado una campaña de cold email.** Tienes un producto o servicio, sabes a quién quieres llegar, pero nunca has construido una lista, escrito una secuencia, ni subido leads a una plataforma de envío. Este skill guía a Claude Code para que te acompañe en todo el proceso paso a paso - desde encontrar empresas hasta monitorizar tus primeras respuestas.

**Ya ejecutas campañas.** Quieres ver cómo una agencia estructura la producción a escala. Los controles de calidad, las capas de validación y los bucles de retroalimentación de este pipeline pueden darte ideas para tu propio proceso.

## Qué necesitas

Este es un stack de producción real, no un juguete. Necesitarás cuentas en estas herramientas:

| Herramienta | Qué hace | ¿Necesaria? |
|-------------|----------|-------------|
| [Claude Code](https://claude.ai/code) | Ejecuta este skill - tu copiloto de IA para todo el proceso. Recomendamos el plan Max de $100/mes como mínimo - este pipeline es intenso y agotará el uso en planes inferiores. | Sí |
| [Smartlead](https://smartlead.ai) | Envía tus emails, gestiona secuencias, rastrea respuestas | Sí |
| [Supabase](https://supabase.com) | Almacena tus empresas, contactos y datos de campaña (el plan gratuito funciona) | Sí |
| [Serper](https://serper.dev) | Investiga empresas vía búsqueda en Google (barato - $0.003/búsqueda) | Sí |
| Un LLM pequeño (tipo GPT-4o-mini, o Claude Haiku para copy sensible al tono) | Generación de variables y revisión de calidad. Usa por defecto el modelo más barato que sirva, fíjalo por prompt y muestra una estimación de coste antes de cada ejecución de pago; lee CLAUDE.md antes de subir a uno mayor. | Sí |
| [MillionVerifier](https://millionverifier.com) | Verificación de emails | Recomendada |
| [BounceBan](https://bounceban.com) | Verificación catchall - confirma que existe el buzón individual en un dominio catchall | Recomendada |

### Encontrar contactos: el orden importa más que la herramienta

Las herramientas de contactos hacen dos trabajos que la gente confunde, y hacerlo al revés sale caro.

| Trabajo | Qué tienes | Qué quieres | Empieza aquí |
|---------|-----------|-------------|--------------|
| **Descubrimiento** | Una empresa | Una lista de decisores en ella | [Apollo](https://apollo.io). Su búsqueda de personas es gratis. Filtra los que ya traen email, deduplica contra lo que ya tienes, y solo entonces paga por enriquecer los desconocidos. |
| **Enriquecimiento** | Una persona concreta | Su email verificado | [Prospeo](https://prospeo.io). Mismo coste por crédito que las alternativas, pero el re-enriquecimiento es gratis y no cobra cuando falla, así que sale más barato a la larga. |

Usa [Icypeas](https://icypeas.com) o [Findymail](https://findymail.com) como proveedores adicionales de la cascada cuando tu primera opción falle.

**Para el descubrimiento, combina cinco fuentes a la vez sobre toda la lista:** Prospeo, Apollo, búsqueda con IA en Google (consultas por cargo que Claude lee y verifica), la web de la propia empresa, y bases de datos locales o de nicho (directorios del sector, listados de ferias y eventos). Filtra solo por el país donde trabaja la persona, nunca por cargo, y deja que la IA clasifique los cargos después. El método completo está en la fase 0.3 de `.claude/commands/produce-campaign.md`.

Poner una herramienta de búsqueda de pago en el hueco del descubrimiento nos costó unas 4 veces lo que debería, porque la mayor parte del gasto se fue en gente que ya estaba en nuestra propia base de datos. Búsqueda gratis, deduplicar, y después pagar.

**No repitas el descubrimiento sobre la misma lista de empresas antes de 90 días.** Devuelve alrededor de un 5% de hallazgos nuevos a precio completo.

**¿Empezar con lo mínimo?** Claude Code + Smartlead + Supabase + Serper + Apollo cubre envío, almacenamiento, investigación y búsqueda de contactos. Añade un verificador antes de enviar nada a nadie.

### Qué cubre esto

Este es un pipeline de **email**. Todo lo que hay aquí (la estructura de la secuencia, la longitud del copy, el tope de destinatarios por empresa, los periodos de espera) asume email y un servidor de correo receptor.

Si más adelante añades otro canal, lo que no se traslada es: el tope por empresa (es una restricción del servidor de correo, no una regla del outbound), las normas de longitud de mensaje, y las reglas de deduplicación, porque una persona puede estar legítimamente en una cohorte de email y en una social en momentos distintos. Decide el canal desde el principio en lugar de añadirlo después, porque casi todas las fases se ramifican según eso.

### Comprobación de spam

El pipeline incluye una fase de comprobación de spam antes de cada push. En lugar de construir tu propia base de datos de palabras spam, puedes usar nuestro [MCL Spam Word Checker](https://mycoldleads.com/spam-checker) gratuito - una base de datos de palabras de spam actualizada en tiempo real a partir de múltiples proveedores. El skill referencia esta herramienta en el paso de comprobación de spam.

## Cómo instalar

1. Clona este repo (o simplemente descarga los archivos)
2. Copia el directorio `.claude/` completo en la raíz de tu proyecto: los comandos, los hooks y sus tests. Si ya tienes un directorio `.claude/`, combínalo en lugar de sustituirlo.
3. Copia `scripts/`, `prompts/` y `setup/` en la raíz de tu proyecto
4. Copia `CLAUDE.md` a la raíz de tu proyecto (o combínalo con tu CLAUDE.md existente)
5. Activa los hooks: añade las entradas de `.claude/settings.example.json` a tu `.claude/settings.json` (ver "Las puertas se cumplen" más abajo) y ejecuta `bash .claude/hooks/tests/run-tests.sh`
6. Ejecuta el SQL de `setup/schema.sql` en el editor SQL de tu Supabase para crear las tablas necesarias. Se puede volver a ejecutar sin riesgo y actualiza una instalación anterior.
7. Copia `setup/campaign-config.template.md` una vez por cliente y rellénalo
8. Abre Claude Code y escribe `/produce-campaign TuNombreDeEmpresa`

Eso es todo. Claude te guiará en cada fase.

## Cómo funciona

El pipeline tiene 14 fases. Cada fase tiene una puerta de control - no puedes avanzar sin completarla.

1. **Configuración de sesión** - Cargar la configuración del cliente, comprobar la salud del TAM, verificar la frescura de los datos
2. **Selección de contactos** - Elegir contactos por persona, aplicar filtros de calidad, puntuar la lista, deduplicar
3. **Validación de emails** - Buscar y verificar direcciones de email a través de un waterfall de proveedores
4. **Preparación de datos de empresa** - Normalizar nombres de empresa, investigar empresas, confirmar que la web pertenece a la empresa, persistir datos
5. **Infraestructura de campaña** - Configurar campañas en Smartlead, asignar dominios, cargar secuencias, blindar los ajustes de entregabilidad
6. **Generación de variables** - Generar observaciones personalizadas, puentes y bullets usando IA
7. **Validación pre-push** - Comprobación de spam, DNC, dedup entre campañas, barrido de calidad, y una revisión de ~40-48 emails reales renderizados al completo que hay que aprobar antes del push
8. **Push a Smartlead** - Cargar leads con campos personalizados a través del wrapper push-safe, verificar cantidades, registrar el contacto
9. **Revisión de calidad con IA** - Subagente Haiku revisa cada email renderizado, no solo los campos
10. **Verificación post-push** - Comprobación final contra datos en vivo de Smartlead
11. **Lanzamiento** - Activar campañas (requiere tu aprobación explícita)
12. **Monitorización post-lanzamiento** - Revisiones a las 24 horas, a los 7 días y a los 14 días de rebotes, respuestas y entrega
13. **Bucle de retroalimentación** - Analizar respuestas positivas para afinar el targeting futuro
14. **Retrospectiva** - Recoger lo que falló en esta ejecución y arreglar el pipeline, no solo la campaña

Cada fase reporta sus resultados y pregunta antes de continuar. El pipeline está diseñado para detectar problemas pronto - antes de que lleguen a las bandejas de entrada de tus leads.

Las barreras que parecerán excesivas hasta la primera vez que te salven: la revisión de emails reales antes del push (Fase 7), el contrato de abstención que deja a la IA decir "no lo sé" en lugar de inventar (Fase 6), y confirmar que la web que investigaste pertenece de verdad a la empresa a la que escribes (Fase 4).

## Una nota sobre calidad

Este pipeline es opinionado. Te impedirá enviar datos malos, saltarte pasos o lanzar sin validación. Eso es intencional.

El cold email mal hecho daña tu dominio, tu reputación y la industria. Bien hecho, es la forma más eficiente de iniciar conversaciones con personas que necesitan lo que vendes.

Las reglas de calidad de este pipeline (nivel de lectura de 5o de primaria, test de conversación de bar, jerga corporativa prohibida, observaciones de un solo dato) vienen de ejecutar campañas reales para clientes reales y medir qué pasó: qué generó respuestas y qué acabó en spam.

## Escalar más allá de Claude Code

Claude Code es el sitio adecuado para **diseñar, probar e iterar** este pipeline. No es el sitio para ejecutarlo a mano 52 semanas al año.

Cada una de las 14 fases anteriores es un bloque listo para convertirse en un workflow de n8n - un paso con una sola responsabilidad, entrada clara y salida clara. Cuando hayas ejecutado el pipeline a mano suficientes veces para que los prompts sean estables y las salidas predecibles, gradúa cada fase a tu infraestructura programada:

- **n8n / Make** - para orquestación de workflows entre fases
- **Railway / Fly / Modal** - para scripts de larga duración (la cascada de emails de la Fase 3, la generación de variables de la Fase 6)
- **cron / pg_cron / Inngest** - para el trabajo recurrente (cadencia de push de nuevos leads, auditoría semanal, retrospectiva trimestral)
- **Supabase** - ya es donde vive tu estado; las fases leen y escriben aquí

El patrón:

```
Claude Code          = diseñar + probar + iterar + escalar incidentes
n8n / Railway / cron = ejecutar + programar + escalar volumen
```

Mantienes el skill en Claude Code para la siguiente ronda de iteración. Dejas de ejecutarlo a mano los lunes. Si nunca gradúas el pipeline, tú te conviertes en el cuello de botella - cada ejecución manual es una semana que podrías haber usado para estrategia, conversaciones con clientes o dormir.

**No gradúes hasta que:** tus prompts hayan pasado dos rondas consecutivas de test sin ediciones (ver el bucle de 10 ejemplos en el skill), hayas ejecutado el pipeline completo a mano al menos 3 veces con salida consistente, y puedas describir los modos de fallo de cada fase. Automatizar un pipeline roto solo escala el error.

**Cuando gradúes, pon un cortacircuitos en cada proceso desatendido.** Un fallo puede ser puntual. Un segundo fallo consecutivo significa parar todo, y no hay tercer reintento. Cuenta los fallos en un sitio que sobreviva a un reinicio, comprueba el contador antes de la llamada de riesgo, y que solo una persona pueda rearmarlo. Pon la política de reinicio de la plataforma en "nunca" o como mucho un reintento; lo habitual por defecto son diez. Los fallos de autenticación, los límites de tasa y el gasto se acumulan con cada reintento, así que cada reinicio automático empeora la situación en vez de arreglarla. El nuestro reintentó un login en un servicio externo cinco veces en noventa segundos y consiguió que invalidaran la sesión de la cuenta.

## Prompts de ejemplo

El directorio `prompts/` incluye prompts iniciales para:
- Normalización de nombres de empresa
- Generación de observaciones (líneas de apertura personalizadas)
- Frases puente (conectando tu observación con tu oferta)

Son puntos de partida. Los iterarás para tu ICP y oferta específicos. El skill te guía a través de un bucle de prueba (10 ejemplos -> feedback -> iterar -> validar en 50 -> producción) para asegurarse de que tus prompts son sólidos antes de ejecutar a escala.

## Idioma

Este skill fue construido para campañas en español. Todos los ejemplos y listas de palabras prohibidas están en español. La metodología y la estructura del pipeline funcionan en cualquier idioma - solo tendrás que adaptar las reglas de copy, las palabras prohibidas y los prompts de ejemplo para tu idioma objetivo.

La comprobación de variación del copy ignora los saludos, las despedidas y las líneas de baja con patrones en español e inglés. Para otro idioma, pasa los tuyos con `--exclusions`, como fichero JSON o en línea. Las claves que no indiques mantienen su valor por defecto:

```bash
python3 scripts/check-copy-variation.py --rendered rendered.json --client ACME \
  --exclusions '{"greeting": "^(bonjour|salut)\\b[^.!?,]{0,30}$", "signoff": "^(cordialement|bien à vous)$", "unsubscribe": "désinscri"}'
```

## Las puertas se cumplen, no solo se documentan

El skill describe 14 fases con un control en cada una. El markdown es un consejo -
un agente puede leer una regla y saltársela igualmente, y no te enteras hasta que
los correos ya han salido. Por eso las reglas que cuestan dinero de verdad también
van cableadas como hooks PreToolUse, que rechazan la llamada directamente.

Copia las entradas de `.claude/settings.example.json` dentro de tu propio
`.claude/settings.json` para activarlas. Si ya tienes un settings.json, añade las
entradas dentro de los arrays en lugar de sustituir el fichero.

| Hook | Rechaza | Marcador para saltarlo |
|---|---|---|
| `pretooluse-push-safe-required.sh` | Desactivar la lista de bloqueo de la plataforma (esto nunca se puede saltar), y subidas de leads en crudo que se saltan el wrapper de deduplicación y espera (`scripts/push-safe.py`). Es una protección, no un entorno aislado: cualquier script llamado `push-safe.*` se considera de confianza | `PUSH_SAFE_OK:` |
| `pretooluse-deliverability-hardening.sh` | Enviar, activar o ejecutar `push-safe.py --apply` sin una prueba de blindaje reciente. Cuando una lectura en vivo muestre el tracking de aperturas y clics apagado y el texto plano encendido, regístralo con `touch .claude/campaign-state/hardening-<campaign_id>.ok`. La prueba caduca a los `HARDENING_MAX_AGE_MIN` minutos (120 por defecto) | `HARDENING_OK:` |
| `pretooluse-custom-field-syntax.sh` | Spintax, tokens de firma, o una variable metida dentro de spintax, en el valor de un campo personalizado | `CUSTOM_FIELD_OK:` |
| `pretooluse-abstention-guard.sh` | Que el token `NOT_FOUND` llegue a un envío dirigido a un lead | `ABSTENTION_OK:` |
| `pretooluse-prompt-cache-guard.sh` | Un bucle de llamadas a un modelo sin `cache_control` en el bloque de sistema. Es específico de Anthropic: OpenAI cachea automáticamente los prefijos largos, así que por defecto solo vigila el endpoint de Anthropic (`LLM_ENDPOINT_RE`) | `CACHE_OK:` |
| `pretooluse-durable-writes.sh` | Un bucle que gasta dinero por registro y guarda solo al final | `DURABLE_WRITES_OK:` |

Cada salto queda escrito en un log junto a los hooks. Usar uno en producción es un
fallo de quien llama, no una solución.

### Compruébalo antes de fiarte

```bash
bash .claude/hooks/tests/run-tests.sh
```

30 casos: a cada puerta se le da una entrada mala que debe rechazar y una buena que
debe dejar pasar. Una puerta que nunca se ha puesto en rojo puede estar
funcionando, o puede no estar haciendo nada - así lo distingues. Ese harness
encontró dos fallos reales en estos hooks antes de publicarlos.

Son bash y Python, sin dependencias. Léelos, son cortos.

### El wrapper de push

`scripts/push-safe.py` es la única vía autorizada para cargar leads en Smartlead. Es una simulación salvo que pases `--apply`. Descarta emails no válidos, repeticiones de la misma persona y a cualquiera dentro del periodo de espera de 90 días, fuerza a false los ajustes de supresión, envía en lotes de hasta 1.000, concilia contra `total_leads`, escribe el registro de contacto en el momento del push e informa de `attempted / succeeded / failed / skipped` con motivos. Lee el periodo de espera de tu tabla `outreach_log` (`DATABASE_URL`, necesita `psycopg`) o de una exportación JSON (`--outreach-log`).

```bash
python3 scripts/push-safe.py --campaign 1234567 --client ACME --leads leads.csv --outreach-log outreach_log.json
python3 scripts/tests/test-push-safe.py   # demuestra la espera, la deduplicación y los ajustes forzados, sin red
```

### Variables de entorno

| Variable | La usa | Por defecto | Qué hace |
|---|---|---|---|
| `SMARTLEAD_API_KEY` | `scripts/push-safe.py --apply`, `scripts/check-copy-variation.py --campaign` | ninguno | Tu API key de Smartlead |
| `DATABASE_URL` | `scripts/push-safe.py` | ninguno | Cadena de conexión de Postgres para la tabla `outreach_log` (lectura del periodo de espera, escritura en el momento del push). Si no tienes acceso directo a la base de datos, usa `--outreach-log FICHERO.json` |
| `PUSH_SAFE_WRAPPER` | hook push-safe | `push-safe` | Nombre base de tu wrapper de push, si lo renombraste o escribiste el tuyo |
| `HARDENING_MAX_AGE_MIN` | hook de blindaje de entregabilidad | `120` | Minutos que es válida una prueba de blindaje |
| `ABSTENTION_TOKEN` | hook de abstención | `NOT_FOUND` | El token que devuelven tus prompts cuando la fuente no respalda una respuesta |
| `LLM_ENDPOINT_RE` | hook de caché de prompt | `api\.anthropic\.com/v1/messages` | Regex de los endpoints de modelos que vigila el hook |

### La comprobación de variación del 15%

`scripts/check-copy-variation.py` mide tus emails FINALES, con los campos personalizados rellenados y el spintax resuelto, y bloquea el push cuando una línea del cuerpo llega a más del 15% de los destinatarios, cuando una línea es idéntica para todos, o cuando menos del 90% de los emails son distintos entre sí. Lee un JSON con tus plantillas y leads antes de enviar, o una campaña de Smartlead ya cargada. Las reglas completas, el formato de entrada y un prompt para hacer la misma comprobación con Claude o Codex están en la sección 7.1 de produce-campaign.

```bash
python3 scripts/check-copy-variation.py --rendered rendered.json --client ACME
bash scripts/tests/test-check-copy-variation.sh   # demuestra que falla con copy repetido
```

---

## Créditos

Creado por [Jack Kelly](https://www.linkedin.com/in/jack-kelly-my-cold-leads/) en [MyColdLeads](https://mycoldleads.com).

Nuestra metodología de copywriting ha sido moldeada por varios profesionales cuyo trabajo admiramos y recomendamos:
- **Eric Nowoslawski** ([Growth EngineX](https://www.youtube.com/@GrowthEngineX)) - copy de cold email, estrategia de personalización y buenas prácticas de entregabilidad
- **Josh Braun** - estructura de email y tono conversacional
- **ColdIQ** ([coldiq.com](https://coldiq.com)) - targeting basado en señales y clasificación de señales de venta

Sígueme en LinkedIn para más herramientas y publicaciones sobre nuestro stack.

## Registro de cambios

**Septiembre 2026** - La sección 7.1 es ahora la comprobación de variación completa que pasamos antes de cada push: ninguna línea del cuerpo en más del 15% de los emails finales, cero líneas fijas y un 90% de emails distintos, con el script (`scripts/check-copy-variation.py`) y su test. Sustituye a las antiguas pautas de "~5 flujos de variación" y "3-5 puntos de spintax por frase". Además, el skill vuelve a reflejar cómo trabajamos de verdad: una revisión de emails reales con variantes de asunto bloquea cada push, la investigación escasa baja al contacto a un opener mínimo con fuente en lugar de sacarlo de la cohorte, los puentes elogian un logro y se revisan para que no se repitan, y hay nuevas barreras para emails caducados, exclusiones excesivas del ICP, nombres del saludo, siglas inventadas, de quién es la noticia, la estructura de la secuencia y su rotación. También hemos quitado cifras internas de los ejemplos, el esquema ya coincide con todas las consultas del skill, y publicamos una plantilla de configuración de cliente y un wrapper de push.

**Agosto 2026** - Corregidas seis reglas que la producción desmintió: el contacto se registra ahora en el momento del push y no después del envío, un único periodo de espera de 90 días sustituye al antiguo reparto de 40/60 días, la deduplicación entre campañas mira el historial de envío en lugar de la pertenencia a una campaña, el descubrimiento de contactos empieza por búsqueda gratuita antes que de pago, los modelos por defecto bajan al modelo pequeño con caché de prompt obligatoria, y saltarse la lista de bloqueo de la plataforma queda explícitamente prohibido. Añadidos el contrato de abstención, la investigación con cita de fuente, la comprobación de identidad de empresa, el blindaje de entregabilidad, la escritura durable, los cortacircuitos y una retrospectiva de ejecución. Corregidas tres tablas que el skill consultaba y que el SQL de instalación nunca creaba.

**Abril 2026** - Publicación inicial.

## Licencia

MIT - úsalo, modifícalo, compártelo. Si te ayuda a conseguir tu primer cliente o a mejorar tus campañas, con eso nos basta.
