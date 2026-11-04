import type { ToolRun } from './types';

const labels: Record<string, string> = { genie_structured_data_tool: 'Genie', project_rag_tool: 'Project search' };

export function ToolDetails({ tools }: { tools?: ToolRun[] }) {
  tools = tools?.filter(tool => tool.name !== 'contract_rag_tool');
  if (!tools?.length) return null;
  return <details className="tool-details"><summary>Tools used · {tools.length}</summary>
    {tools.map(tool => <div className="tool-result" key={tool.id}>
      <div><strong>{labels[tool.name] || tool.name}</strong><span role="status">{tool.status === 'completed' ? 'Result received' : tool.status === 'error' ? 'Failed' : tool.status === 'unavailable' ? 'Result not provided' : tool.status === 'stopped' ? 'Stopped' : 'Running'}</span></div>
      <pre>{tool.input}</pre>
      {tool.output && <details><summary>View result</summary><pre>{tool.output}</pre></details>}
    </div>)}
  </details>;
}
