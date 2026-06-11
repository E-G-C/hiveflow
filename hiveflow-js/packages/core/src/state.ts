import type { WorkflowData } from "./types.js";

export class WorkflowState {
  private readonly currentState: WorkflowData;
  private readonly previousStates: WorkflowData[];

  constructor(initialState: WorkflowData = {}, history: WorkflowData[] = []) {
    this.currentState = { ...initialState };
    this.previousStates = history.map((entry) => ({ ...entry }));
  }

  merge(updates: WorkflowData): WorkflowState {
    return new WorkflowState(
      {
        ...this.currentState,
        ...updates
      },
      [...this.previousStates, { ...this.currentState }]
    );
  }

  get<TValue = unknown>(key: string): TValue | undefined {
    return this.currentState[key] as TValue | undefined;
  }

  snapshot(): WorkflowData {
    return { ...this.currentState };
  }

  get history(): WorkflowData[] {
    return this.previousStates.map((entry) => ({ ...entry }));
  }
}