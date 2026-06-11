import { Agent, HiveFlow, WorkflowEngine } from "@hiveflow/core";

import {
    createLiveModelAdapter,
    resolveLiveExampleConfig,
    summarizeLiveExampleConfig
} from "../../shared/live.ts";

const live = resolveLiveExampleConfig();

const researcher = new Agent({
    id: "researcher",
    role: "Researcher",
    instructions: "Collect exactly three concise factual notes for the current task.",
    model: createLiveModelAdapter({ ...live, id: "sequential-researcher" }),
    behavior: "llm_only"
});

const writer = new Agent({
    id: "writer",
    role: "Writer",
    instructions: "Write a short two-paragraph synthesis from the current workflow state.",
    model: createLiveModelAdapter({ ...live, id: "sequential-writer" }),
    behavior: "llm_only",
    prompt: (state) =>
        `Task: ${String(state.task ?? "")}\nResearch: ${String(state.researcherOutput ?? "")}`
});

const workflow = new WorkflowEngine({
    steps: [
        {
            id: "research",
            agent: "researcher",
            type: "sequential",
            next: "write"
        },
        {
            id: "write",
            agent: "writer",
            type: "sequential"
        }
    ]
});

const hiveflow = new HiveFlow();
const result = await hiveflow.run({
    workflow,
    agents: { researcher, writer },
    initialState: {
        task: "Explain why renewable energy matters."
    }
});

console.log(
    JSON.stringify(
        {
            live: summarizeLiveExampleConfig(live),
            result
        },
        null,
        2
    )
);