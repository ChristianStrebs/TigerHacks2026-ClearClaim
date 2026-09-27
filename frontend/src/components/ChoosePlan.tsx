import { Icon } from "../Icon";

export function ChoosePlan({
  disabled,
  onOwnPlan,
  onSample,
}: {
  disabled: boolean;
  onOwnPlan: () => void;
  onSample: () => void;
}) {
  return (
    <section className="choose-plan" aria-labelledby="choose-plan-title">
      <h2 id="choose-plan-title">How would you like to start?</h2>
      <p>
        Add your own benefits for real answers, or try made-up sample data to
        see how ClearClaim works.
      </p>
      <button className="question-card" disabled={disabled} onClick={onOwnPlan}>
        <span className="mini-icon own">
          <Icon name="upload" />
        </span>
        <span>
          <small>RECOMMENDED</small>
          <strong>Use my own plan</strong>
          <span className="choose-detail">
            Upload or paste your benefits summary
          </span>
        </span>
        <Icon name="chevron" size={17} />
      </button>
      <button className="question-card" disabled={disabled} onClick={onSample}>
        <span className="mini-icon">
          <Icon name="spark" />
        </span>
        <span>
          <small>JUST LOOKING</small>
          <strong>Try with sample data</strong>
          <span className="choose-detail">
            A made-up plan and bill, clearly labeled
          </span>
        </span>
        <Icon name="chevron" size={17} />
      </button>
    </section>
  );
}
