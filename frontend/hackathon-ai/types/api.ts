export type Language = 'python' | 'cpp';
export type EventType = 'status' | 'sandbox_result' | 'final_solution' | 'error';

export interface TestCase {
  input: string;
  expected_output: string;
}

export interface ExecutionRequest {
  problem_description: string;
  language: Language;
  max_iterations: number;
  time_limit_seconds: number;
  test_cases: TestCase[];
}

export interface StreamEvent {
  event_type: EventType;
  message: string;
  iteration?: number;
  code_snippet?: string;
  passed?: boolean;
}
