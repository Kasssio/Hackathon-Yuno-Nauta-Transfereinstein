# Arquitectura — Volta

> Diagrama en Mermaid: GitHub lo renderiza solo y se edita como texto, sin
> reexportar una imagen cada vez que cambia algo. El PNG anterior
> (`arquitectura.png`) quedó del Bloque 2 y ya no refleja el sistema.

## El sistema

```mermaid
flowchart LR
    subgraph mundo["Mundo real"]
        chofer["Transportista<br/>o chofer"]
        humano["Operador humano<br/>toma casos escalados"]
    end

    subgraph tel["Telefonía"]
        twilio["Twilio<br/>disca el número"]
    end

    subgraph openai["OpenAI"]
        sip["Endpoint SIP"]
        rt["Realtime API<br/>speech-to-speech"]
    end

    subgraph voz["voice/ — server de voz"]
        ctrl["WebSocket de control<br/>transcripciones y tool calls"]
        tools["Manejador de tools"]
    end

    subgraph back["backend/ — FastAPI"]
        neg["Motor de negociación<br/>qué monto se puede ofrecer"]
        guard["Guardrail de mandato<br/>monto ≤ tope · fecha ∈ ventana"]
        carriers["Base de transportistas<br/>30 · puntaje ponderado"]
        estado[("Estado<br/>operación · mandato<br/>cotizaciones · commitments")]
        trail[("Trail auditable<br/>append-only, hash encadenado")]
    end

    dash["dashboard/<br/>vista humana en vivo"]

    chofer <-->|voz| twilio
    twilio -->|"Dial + Sip"| sip
    sip <-->|audio| rt
    rt <-->|eventos| ctrl
    ctrl --> tools

    tools -->|find_carriers| carriers
    tools -->|evaluar_negociacion| neg
    tools -->|record_commitment| guard
    guard -->|sólo si aprueba| estado
    neg -.->|lee el mandato| estado
    estado --> trail

    estado <-->|"lee y escribe"| dash
    dash -->|"revocar mandato<br/>(trial by fire)"| estado
    tools -.->|escalate_to_human| dash
    dash <--> humano

    classDef codigo fill:#e8f5e9,stroke:#2e7d32,color:#1b5e20
    classDef modelo fill:#ede7f6,stroke:#5e35b1,color:#311b92
    classDef datos fill:#eceff1,stroke:#546e7a,color:#263238
    class neg,guard codigo
    class rt modelo
    class estado,trail,carriers datos
```

**Verde = decisiones que toma código, no el modelo.** Es el punto central del
diseño: el LLM decide *cómo* conversar, el código decide *qué* está permitido.

## Recorrido de una llamada

```mermaid
sequenceDiagram
    autonumber
    participant D as Dashboard
    participant T as Twilio
    participant V as Volta
    participant C as Transportista
    participant B as Backend

    D->>T: POST /call/start
    T->>C: disca
    C-->>T: atiende
    T->>V: puentea por SIP
    V->>B: get_operacion_actual · find_carriers · check_mandato
    B-->>V: operación, candidatos y mandato vigente
    V->>C: "Hola [nombre], necesito un camión de..."
    C-->>V: contraoferta
    V->>B: evaluar_negociacion(oferta)
    B-->>V: contraoferta autorizada o cortar
    Note over V,B: El modelo nunca calcula el monto
    V->>C: contraoferta
    C-->>V: acepta
    V->>B: record_commitment
    B->>B: guardrail: monto ≤ tope · fecha ∈ ventana
    alt aprobado
        B-->>D: commitment confirmado
    else rechazado o fuera de mandato
        B-->>D: motivo del rechazo
        V->>D: escalate_to_human
        Note over V,C: Volta NO corta: queda en modo escucha
        D-->>B: un humano confirma el borrador
    end
```

## Por qué SIP y no Media Streams

Las dos formas de conectar Twilio con un agente de voz:

| | Media Streams | **SIP** (lo que usamos) |
|---|---|---|
| Camino del audio | Twilio → nuestro server → OpenAI | Twilio → OpenAI, directo |
| Transcodificación | μ-law 8kHz en los dos sentidos, en tiempo real | ninguna |
| Latencia agregada | la de nuestro puente | ninguna |
| Nuestro WebSocket | transporta audio | sólo control: transcripciones y tool calls |
| Si nuestro server se cae | se corta el audio | la conversación sigue |

## El trial by fire

`POST /mandatos/{id}/revocar` revoca el mandato en vivo, desde el dashboard.
Funciona porque el agente vuelve a llamar a `check_mandato` **antes de cada
commitment**, no sólo al arrancar la llamada: una revocación a mitad de
conversación aterriza en el siguiente intento de cerrar, y el guardrail la
hace valer aunque el modelo ya hubiera aceptado de palabra.
