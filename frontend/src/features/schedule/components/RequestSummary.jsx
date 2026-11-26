import { conditionRows } from "../formatSchedule.js";

export default function RequestSummary({ session, catalog, comparison }) {
  const draft = session?.draft;
  const collecting = session?.status === "needs_clarification" && draft && Object.keys(draft).length > 0;
  const source = collecting ? draft : session?.request;
  if (!source) return null;
  const rows = conditionRows(source, catalog);
  const comparing = !collecting && comparison?.after.request.revision === session.request.revision;
  if (comparing) {
    const before = new Map(conditionRows(comparison.before.request, catalog).map((row) => [row.key, row]));
    const after = new Map(rows.map((row) => [row.key, row]));
    const keys = [...new Set([...after.keys(), ...before.keys()])];
    const changes = keys.map((key) => ({ key, label: after.get(key)?.label || before.get(key).label,
      previous: before.get(key)?.value || "이번 조회에 사용하지 않음", value: after.get(key)?.value || "이번 조회에 사용하지 않음" }));
    const changed = changes.filter((row) => row.previous !== row.value);
    const kept = changes.filter((row) => row.previous === row.value);
    return <section className="request-understanding"><h3>조건 변경 확인</h3>
      {changed.length ? <><h4>바뀐 조건</h4><table className="data-table compact condition-comparison"><thead><tr><th>조건</th><th>변경 전</th><th>현재</th></tr></thead><tbody>{changed.map((row) => <tr key={row.key}><th scope="row">{row.label}</th><td>{row.previous}</td><td>{row.value}</td></tr>)}</tbody></table></> : <p className="help-text">요청 조건을 유지하고 제안을 다시 확인했습니다.</p>}
      {!!kept.length && <><h4>유지한 조건</h4><dl className="request-summary">{kept.map((row) => <div key={row.key}><dt>{row.label}</dt><dd>{row.value}</dd></div>)}</dl></>}
    </section>;
  }
  return <section className="request-understanding"><h3>{collecting ? "확인 중인 조건" : session?.status === "needs_clarification" ? "현재 유지한 조건" : "이해한 회의 조건"}</h3>
    {collecting && <p className="help-text">지금까지 읽은 내용입니다. 확인이 필요한 조건을 보완해주세요.</p>}
    <dl className="request-summary">{rows.map((row) => <div key={row.key}><dt>{row.label}</dt><dd>{row.value}</dd></div>)}</dl>
  </section>;
}
