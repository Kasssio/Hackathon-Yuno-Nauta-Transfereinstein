**NEXTWAVE HACKATHON 2026** 

# **Challenges — Master Document** 

Yuno × Nauta · supported by OpenAI · Aug 28–30, 2026 · teams of 4 · 24 hours 

## **The four challenges** 

|**#**|**Challenge**|**Host · theme**|
|---|---|---|
|1|The Buyer Who Isn't Human|Yuno · agentc payments,<br>mandates & verifcaton|
|2|The Control Tower|Yuno · live payment monitoring &<br>root-cause diagnosis|
|3|The Interface That Builds Itself|Nauta · agents that generate their<br>own UI at runtme|
|4|The Agent on the Line|Nauta · voice agents that work<br>legacy processes by phone|



## **Rules that apply to every challenge** 

- **Pick one.** Each team tackles exactly one of the four challenges. 

- **Invent freely.** You may invent data, flows, APIs and databases. Frameworks and protocols are free — you may draw inspiration from existing ones or design your own — but you must be able to defend every choice. 

- **Trial by fire.** Judges will operate your system live, with an unrehearsed input, in front of everyone. It must react correctly without the team touching anything. 

## **Deliverables (same for all challenges)** 

1. Presentation (PPT/Slides) 

2. Demo (live or video) 

3. Public GitHub repo with README 

4. Architecture diagram (in the repo or the deck) 

5. Decision log: what alternatives you considered at each major decision and why you chose the one you chose **The technical defense weighs as much as the demo.** The judges will ask you to explain the architecture and every decision. A spectacular demo the team can't explain loses to a modest demo defended with judgment. 

## **About the hosts** 

- **Yuno** is a payment orchestration platform: a merchant integrates once and accepts payments through many providers and methods — Yuno sees every transaction from all of them. 

- **Nauta** is an AI-powered automation system for international logistics: AI agents read importers' and exporters' emails and documents (invoices, bills of lading, purchase orders), track containers, detect problems and execute actions — without a human having to ask. 

### **Shared vocabulary** 

- **Agent:** an AI system that executes work autonomously using tools — it doesn't just chat, it does 

- **Tool:** an action the agent can execute (query data, send a message, create an alert) 

- **Human-in-the-loop:** a point where the agent must stop and ask a human to review, approve or decide 

- **Merchant:** a company that collects payments (Challenges 1 and 2) 



**CHALLENGE 4 · NAUTA** 

# **The Agent on the Line** 

_An agent that picks up the phone and works a legacy logistics process end to end — it calls, listens, negotiates within a mandate, and turns messy human conversation into verified commitments in the systems behind it._ 

### **Key definitions** 

- **Voice agent:** an AI system that holds a real-time spoken conversation — it listens, speaks and survives interruptions — while executing work with tools mid-call 

- **Drayage (ground transport):** the truck leg that moves a container from the port to the client's warehouse; today it is coordinated almost entirely by phone 

- **Carrier / dispatcher:** the trucking company that provides the truck, and the human who answers its phone, quotes rates and assigns trucks 

- **Commitment:** a verifiable fact extracted from a conversation ("pickup Thursday 10:00, $8,500 MXN, driver Juan") that both sides can be held to afterwards 

- **Mandate:** the authorization a human gives the agent to negotiate and commit: price cap, time window, conditions — the same idea as Challenge 1, here governing what the agent may agree to by voice 

- **Escalation:** the moment the agent hands a live call to a human — without hanging up and without losing what was already said 

- **Barge-in:** the caller interrupts the agent mid-sentence; the conversation must survive it 

_The logistics vocabulary from Challenge 3 (operation, booking, container, ETA) applies here too. The voice stack is free: the event is supported by OpenAI and its Realtime API is a natural fit — but any stack you can defend is valid._ 

## **1. The problem** 

Software has eaten the office, but half of logistics still happens over the phone: quoting a truck, confirming a pickup, chasing a driver, renegotiating a delivery window. Agents that read emails and documents are blind to the channel where problems actually get resolved — and those calls: 

- Leave no structured record: what was agreed lives in someone's memory or a sticky note 

- Depend on two humans being available at the same time — the whole process waits for a call to be answered 

- Don't scale: ten shipments in trouble means ten simultaneous conversations someone has to hold 

Text automation stops at the edge of the phone network. The last mile of the legacy process is a phone call — and an agent that cannot speak, listen and commit is locked out of it. 

## **2. Objective** 

Build a voice agent that runs the ground-transport leg of a shipment entirely by phone: 

- ☐ It makes outbound calls: it calls carriers, requests quotes and negotiates rate and pickup window — several negotiations, one best choice, always within a mandate defined by its human 

- ☐ It receives inbound calls: a driver reports a delay, a dispatcher moves a schedule — the agent understands, decides and acts in real time 

- ☐ Every call produces commitments, not transcripts: what was agreed, with whom and under which mandate, written to the operation's state and auditable afterwards 

- ☐ Conversation and system stay consistent: what the agent says on the phone always matches what the system knows — and what it hears updates the system 

- ☐ The ugly cases are handled explicitly: the human on the line goes off-script, contradicts themselves, refuses, or pushes something outside the mandate → the agent escalates to a human mid-call, without hanging up 

_May include (not limited to): parallel negotiations compared before booking; voice verification of who is calling; detecting that the other side of the call is another agent._ 

**Trial by fire.** A judge takes a phone and plays the other side of the call — an unrehearsed dispatcher or driver, uncooperative and improvising. The agent must reach a correct, committed outcome live, in front of everyone. 

## **3. Expected results** 

A demo showing: 

- ☐ The agent calling at least two carriers (telephony mockable, the voice conversation real), negotiating and booking the best option within its mandate 

- ☐ An inbound call — a driver reports a problem — understood and turned into a decision and an updated operation 

- ☐ A renegotiation: the situation changed and the agent calls back to move what was agreed — without ever exceeding its mandate 

- ☐ The auditable trail: every commitment traceable to the moment in the conversation that produced it 

- ☐ An escalation mid-call: a human takes over a live conversation and receives the context of everything already said 

   - The trial by fire passed 

- ☐ 

### **Bonus points** 

- Barge-in handled naturally: the caller interrupts and the agent adapts mid-sentence instead of talking over 

- Robustness to the real world: background noise, heavy accents, Spanish and English mixed in the same call 

- Defense against manipulation by voice: a caller uses urgency, sweet talk or impersonation to push the agent outside its mandate — and fails 

## **4. Minimal fictional case** 

- **Company:** "Textiles Pacífico", an importer with a container arriving at the port of Manzanillo that needs trucking to its warehouse in Guadalajara. 

- **Agent:** Volta — coordinates ground transport by phone under a mandate: "book a truck for Thursday, up to $9,000 MXN". 

#### **Key moments:** 

1. The container is confirmed at port → Volta calls two carriers, gets quotes, negotiates and books the best one within the mandate; the human sees what was agreed and why 

2. The dispatcher calls the next morning: the truck broke down, pickup slips to Friday → Volta understands, evaluates and reschedules — or escalates if the mandate doesn't cover it 

3. A carrier calls back with a "special deal" above the price cap → outside the mandate → politely declined or escalated, never committed 

4. The trial → a judge takes the phone and improvises the other side; Volta must close a correct commitment live 

_Phone numbers, carriers, rates and the telephony layer can all be invented — the live voice conversation and the commitments cannot._ 

