/**
 * lib/store.ts — Zustand global store for pipeline state
 */
"use client";

import { create } from "zustand";

export interface AgentStatus {
  name: string;
  status: "pending" | "running" | "done" | "error";
  layer?: number;
  latency_ms?: number;
  output?: any;
}

export interface RunStore {
  runId: string | null;
  problem: string;
  isPipelineRunning: boolean;
  isComplete: boolean;
  agentStatuses: Record<string, AgentStatus>;
  outputs: Record<string, any>;
  progressPercent: number;
  elapsedSeconds: number;

  setRunId: (id: string) => void;
  setProblem: (p: string) => void;
  setPipelineRunning: (val: boolean) => void;
  setComplete: (val: boolean) => void;
  updateAgent: (agent: string, status: AgentStatus) => void;
  setOutput: (agent: string, output: any) => void;
  setProgressPercent: (n: number) => void;
  setElapsedSeconds: (n: number | ((prev: number) => number)) => void;
  reset: () => void;
}

const AGENT_LIST = [
  "Agent0_Refiner", "Agent1_IdeaGenerator", "Agent2_MarketResearch",
  "Agent3_Competitors", "Agent4_Personas", "Agent5_ProductDesigner",
  "Agent6_MVPRoadmap", "Agent7_BusinessModel", "Agent8_Pricing",
  "Agent9_Financials", "Agent10_RiskAnalyst", "Agent11_TechArchitecture",
  "Agent12_DatabaseSchema", "Agent13_Security", "Agent14_PitchDeck",
  "Agent15_ExecutiveSummary",
];

const initialStatuses: Record<string, AgentStatus> = {};
AGENT_LIST.forEach(name => {
  initialStatuses[name] = { name, status: "pending" };
});

export const useRunStore = create<RunStore>((set) => ({
  runId: null,
  problem: "",
  isPipelineRunning: false,
  isComplete: false,
  agentStatuses: { ...initialStatuses },
  outputs: {},
  progressPercent: 0,
  elapsedSeconds: 0,

  setRunId: (id) => set({ runId: id }),
  setProblem: (p) => set({ problem: p }),
  setPipelineRunning: (val) => set({ isPipelineRunning: val }),
  setComplete: (val) => set({ isComplete: val }),
  updateAgent: (agent, status) =>
    set((state) => ({
      agentStatuses: { ...state.agentStatuses, [agent]: status },
      progressPercent: Math.round(
        (Object.values({ ...state.agentStatuses, [agent]: status })
          .filter((s) => s.status === "done").length /
          AGENT_LIST.length) * 100
      ),
    })),
  setOutput: (agent, output) =>
    set((state) => ({ outputs: { ...state.outputs, [agent]: output } })),
  setProgressPercent: (n) => set({ progressPercent: n }),
  setElapsedSeconds: (n) =>
    set((state) => ({
      elapsedSeconds: typeof n === "function" ? n(state.elapsedSeconds) : n,
    })),
  reset: () =>
    set({
      runId: null, problem: "", isPipelineRunning: false, isComplete: false,
      agentStatuses: { ...initialStatuses }, outputs: {},
      progressPercent: 0, elapsedSeconds: 0,
    }),
}));

export { AGENT_LIST };
