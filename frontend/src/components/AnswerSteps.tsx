import { Icon } from "../Icon";
import type { AgentStep, AgentTool } from "../types";

function toolIcon(tool: AgentTool): string {
  switch (tool) {
    case "search_plan":
      return "plan";
    case "get_bill":
      return "scan";
    case "estimate_cost":
      return "wallet";
    case "check_rights":
      return "shield";
    default: {
      const unhandled: never = tool;
      return unhandled;
    }
  }
}

export function AnswerSteps({ steps }: { steps: AgentStep[] }) {
  if (steps.length === 0) return null;
  return (
    <details className="answer-steps">
      <summary>
        How I answered · {steps.length} {steps.length === 1 ? "step" : "steps"}
      </summary>
      <ol>
        {steps.map((step, index) => (
          <li key={index}>
            <span className="step-icon" aria-hidden="true">
              <Icon name={toolIcon(step.tool)} size={14} />
            </span>
            <div>
              <strong>{step.label}</strong>
              <p>{step.result}</p>
            </div>
          </li>
        ))}
      </ol>
      {steps.some((step) => step.tool === "estimate_cost") && (
        <p className="answer-steps-note">
          Costs come from ClearClaim's calculator; the AI never does the math.
        </p>
      )}
    </details>
  );
}
