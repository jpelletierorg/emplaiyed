# Emplaiyed — Requirements Questions

Answer inline below each question. Take as much space as you need.

---

## Architecture & Runtime

**1. Language/runtime preference?** Python, Node/TypeScript, Go, Rust — or no preference? Python has the richest ecosystem for LLM tooling and scraping. TypeScript is strong for CLI + web. Do you have a leaning?

> im not leaning toward anything. you must use the best tool for the job at all time. that could very well mean that you will make the cli in typescript and the llm agents part in python. you are the coder you decide. make sure that you are positioned to make the best possible use of the tool when you make that decision. 

the reason that you are able to make these decision yourself is that AT ALL TIME, you are going to write tests for what you are doing. everything you do must be tested. if you make a ui, i want you to actually test it yourself and make sure that it meets a certain level of quality before marking things done. you must always pro-actively test stuff and you can never consider someting done unless there is some kind of test involved. on rare occasion, you can leverage me, the human in the loop for tests but this must be when you deem that there are abosolutely no other options for testing. 



**2. LLM backbone** — This tool is clearly AI-heavy (scoring opportunities, drafting outreach, prep Q&A, live assistance). Are you thinking Claude API as the primary LLM? Should it be model-agnostic so you can swap in OpenAI/Gemini/local models?

i was thinking of using claude yes but you will make the tool support different models. in fact, you will create evals that will help you determine what are the best model for each task and that provide the best combination of quality of the result and the price it cost. the general approach will be to create the evals (this is code that encodes what you expect the llm to reply) and use the best available model. once you have something in place that meets the quality criteria, you can do a grid search for a model that is cheaper and that still meets the evals quality threshold. 

>

**3. CLI framework** — Are you envisioning a traditional CLI (`emplaiyed profile build`, `emplaiyed sources scan`, etc.) or more of an interactive/conversational agent you talk to in the terminal? Or both — structured commands for automation, conversational mode for advisory tasks like negotiation?


that is it, both. i would have assumed that the profile building steps would require some kind of conversation with the agent in order for him to collect 
the information he needs from the user to build the profile. i expect that some part of the toolkit will be more automation oriented where you can just invoke them. then some other tools might be services, like something that monitors incoming email replies from employer and schedule the next steps. 

you will know which form is appropriate from wich task a particular part of the toolkit must accomplish.
>

---

## Phase 0: Profile

**4. Profile format** — You mentioned "a file or some other referencable place." I'm thinking a local YAML/JSON/TOML file that the CLI helps you fill out interactively. Is that right, or do you want something more structured like a SQLite DB from the start?

ultimately, this profile is the thing that will store the information about the user and that will inform a lot of other downstream tasks: this is from this information that a custom tailored c.v. will be generated for each job opportunities. it is from that file that the address required to fill forms on employers website will be taken. since this information is meant to occupy the context window of an llm i was thinking of a yaml/json/toml with a preference for some kind of human readable format that a user could edit manually if need be. 

it really is a document but there is a form of schema associated with it. the point is that it must be easily crudable by the agent. 

>

**5. Profile ingestion** — Should the tool be able to bootstrap a profile from an existing CV/resume (e.g. parse a PDF) rather than making you type everything from scratch?

abosolutely, at some part during profile building, the ai should ask for a resume and feed off of that in order to facilitate data entry for the seeker. 

the agent then analyzes what is there and what is not there in the c.v. and formulate the remaining appropriate questions to complete the profile. one example of that is that a cv will often include employment history but not things like date of birth. it is the job of the agent to extract what it can from the c.v. identify the delta from that and the information it will need and then be able to generate a set of questions and manage an interaction with the user that will allow him to gather information that cover that gap. 

>

---

## Phase 1: Sources

**6. Scraping reality check** — LinkedIn and Indeed actively fight scraping. Are you okay with approaches that may be fragile (headless browser, API reverse-engineering) or do you want to start with sources that have actual APIs or RSS feeds? Or are you thinking the user manually pastes job URLs/descriptions and the tool scores them?

For that, we will be practical.... when we work together on the source engine, we will consider what gives the most bang for our buck. it might take the form of 
using an agent that can use a browser to "scrape" jobs as if it was a real user, it can be by trying to find some unofficial api that allow for the collection of 
jobs i dont know yet. 

but we will be bold and creative and we WILL get that information. it might require us to build some browser plugin or whatnot but we will find a way.


>

**7. "Cold call" sourcing** — The dynamic sourcing idea (find regional companies, infer needs, cold outreach) is the most ambitious part. What's the input here? A list of companies? A geographic region + industry? A CRM-like database you build up over time?

so i was thinking that from the user profile and from is intentions captured in it, the agent or subagent would try to find companies, with a preference for 
local companies, that might be amenable to spontaneous candidacy if they where presented with an enticing offer or some reason to believe that the seeker might 
solve one of their pain point. so it will be some kind of deep research that is focused on gathering information about companies and them finding the right people to message, the right channel to do so and the right messaging. 

that is a relatively loosely coupled part of the toolkit so i guess this could be a subproject that we can re define later.

>

**8. Scoring criteria** — You said "scored with respect to some kind of fit criteria." Is this purely LLM-driven (compare job description to profile, return a score) or do you want explicit weighted rules (e.g. salary range worth 30%, tech stack match worth 40%, commute worth 30%)?

well the truth is i do not know.... i dont know which scoring method will ultimately yield the best result. so..... we will need a general scoring function/agent that take a profile and some kind of job object and then that will return a score and that function will be something we can just swap in the future. 

to get the ball rolling, why not start with some purely llm based thing where we force the llm to return a justificatino and a score from 0-100.

>

---

## Phase 2: Outreach

**9. Actual sending vs drafting** — Does the tool *actually send* emails/messages, or does it *draft* them and you hit send? Fully automated outreach is powerful but risky (wrong tone, sent to wrong person, spam filters). What's your comfort level?

the ultimate goal is to have the entire pipeline almost fully automated. from profile to sitting at an office desk with as little human baby sitting as possible. 

when i say automated i mean it. for example, i imagine that the outreach agent could use a voice clone from eleven labs for handling the phone calls. that is how 
far i am willing to automate. so yes i want to agent to send but we will reach that level of automation in steps where, you have hinted at it, we will maybe have a human in the loop at some key points in the process to make sure everything runs smoothly at the beginning. 

also consider that: ai models will get better in the near future. that is guaranteed, so you always need to aim for a framework that supports full automation
because at some point the model will always outperform the human in the loop, at which point handing over responsibility to the model from the human must be has simple as setting a flag to false or commenting a line of code. 

i hope you are starting to see the vision here. if not it would be worht asking more follow up quesitons.

>

**10. Channel integrations** — Email is straightforward (SMTP). LinkedIn messaging requires their API or browser automation. Company job boards are all different. For MVP, which channels matter most?

we will add many channel concurrently. the thing is, i want to see result emerge and create tiny mvp for all of the moving parts of the system so i guess that we will start with email but development will happen in parallel and other channel like linked and al will be implemented too. we will use multiple coding agent to advance in parallel...

does that answer the question?

>

**11. State machine** — The application tracking (applied → followed up → interview scheduled → etc.) — is this something you want stored locally (SQLite, JSON files) or do you envision a web UI dashboard eventually?

good point, there needs to be an interface that allows the user to see the state of is "funnel" for starter that could be a collection of cli tool command that allow me to see what are the number of jobs that i have applied to in total that are in a certain stage but that is a good idea you bring up: maybe at some point we want some kind of visualization bashboard that alow a user to peer in realtime what is happening with the funnel.

i mean how cool would it be to just watch the dashboard update as a collectigon of ai agents send emails and apply to job and secure interviews for you..

it would be a supreme achievement.

>

---

## Phase 3-4: Preparation & Live Assistance

**12. Live call assistance** — This is the most technically complex feature. Are you thinking real-time speech-to-text of the interviewer's questions, then the tool suggests answers on screen? This requires audio capture, STT, low-latency LLM inference. Do you want this in MVP or is it a later phase?

ok so i guess this comes from a vision that there will be part of the system that will be able to act on my behalf. i want the ai agent that represent me to have a phone and be able to use all these api that you mention and deliver assistance to a seeker. imagine that the agent and the seeker can be on the same call and that the agent might answer some live questions on the call while others are answered by the seekr himself.

maybe there is some kind of a bashboard where information is taken from the live phone call and there is a live websocket connection that feeds commentary to the seeker as the interviewer speak.

i dont know exactly what this shyould be but you see this become a nice little side project that can be worked on in parallel while other parts of the system is being built. we will need a full company of AI agent that will be required to build this!!!

the job that you will have is to create detail sub specification for these sub project and delegate or to help me help you delegate to these sub agent.....


>

**13. Preparation scope** — Is this primarily "generate likely interview questions + suggested answers based on company/role" or do you also want mock interview simulations where the AI plays interviewer?

again i feel like this is a sub project where we could add features almost indefinitely. the goal will be to start with the simples things that offers value and grow that subpart of the system gradually while the other parts grow as well. 

just to make things simple, i was thinking that depending on what the next kind of meeting was with the employer (first screening call, second technical interview)
the toolkit and the agent within it might jsut prepare some kind of cheat sheet that would be some kind of "hey, this is what you should expect from that phone screening.... the will ask you x,y,z. i suggest we provide the following answers because bla bla bla"

>

---

## Phase 5-6: Loop & Negotiation

**14. Autonomous follow-ups** — You mentioned the toolkit proactively following up after no response. How autonomous? Fully automatic (sends follow-up email after X days with no response) or "suggests a follow-up and you approve"?

again we go from simple to compolex while not cornering ourself into a desing that will prevent the complex. there will for sure be a human in the loop to start with but not for loong. 

the autonomous thing needs to be able to pro-actively select follow up actions from an opportunities pool that require it and be able to load all of the appropriate context that it needs for the follow up. this could look like "hey, i just wanted to do a quick follow up. I know this is the second time this week and that you have not had time to reply but i just wanted to let you know that i have another opportunity that i have to consider. since i have started the inrweciwq process with you guys earlier, i felt that i should let you the opportunity to make an offer also. let me know if you guys are still interested... "

so you see this requires that the whole pipeline is taken into account (the agent know that there exist an opportunity that the seeker can accept) it also knows that there was already some kind of follow up sent less then a week ago  etc. etc. 

that is the kind of autonomous actions i am expecting. 

>

**15. Multi-offer negotiation** — This is strategic advice territory. Is the tool just tracking offers in a table and you ask it for advice, or do you want it to actively draft negotiation emails/messages?

it should assist in all employer facing negotiation activities. this can be by drafting emails with the help of the seeker, by listening in on phone calls with the employer and flasing live advice as we have discussed earlier. we will settle on an appropriate functional level of assistance for the first version. 

for all of these, these subproject where the real objective is not yet clearly defined (not sure what the level of automation will be etc.) i expect you to make a concrete proposal for what to work on first. 

>

---

## General

**16. Data persistence** — Everything local on disk? Or do you want a server component eventually (for autonomous scheduled tasks like source scanning and follow-ups)?

i mean, this will run on my 24/7 mac mini at home just becaue i am so poor i cannot afford the hosting so that is the environment for execution that you can expect.

>

**17. MVP scope** — Which phases do you want working first? I'd guess Profile + Sources + basic Outreach tracking is the minimum useful thing. The live interview assistance is a different beast entirely. Do you agree, or do you see the MVP differently?

i want you to take all that in and create a DAG of all the dependencies in the subcomponent of this project. then, you will run a topological sort and you will 
suggest what should be worked on first. 

now your topo sort might reveal that many things can be worked out in parallel and that is what i want to be able to do. you and i will cycle through the agent to provide feedback and help unblock them when they are stuck (e.g: need a credit card to buy an ElevenLap api key etc.)

as you have successfully identified, the profile is one thing that will be selectable first. 

>

**18. Multi-user or just you?** — Is this a tool you build for yourself and maybe open-source later, or are you thinking multi-tenant from the start?

i will be the sole user of that at the start yes. if i want to support multiple user i will just run multiple instances of the whole thing in parallel

>
