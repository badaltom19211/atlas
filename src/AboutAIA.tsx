import { BarChart3, Database, FileText, MessageCircle, ShieldCheck } from 'lucide-react';

export default function AboutAIA({ preview, historyStorage }: { preview: boolean; historyStorage: 'local' | 'lakebase' }) {
  return <div className="aia-help">
    <div className="help-intro"><span className="help-mark" aria-hidden="true">AIA</span><div>
      <h3>Your contract assistant</h3>
      <p>Ask questions about contract records and documents, explore the results, and check the evidence behind an answer.</p>
    </div></div>

    <section className="help-section" aria-labelledby="help-sources"><h3 id="help-sources">Data sources</h3>
      <div className="help-source-grid">
        <div><Database size={19} aria-hidden="true" /><h4>Structured records · Genie</h4><p>Queries the tables configured in the connected Genie agent for counts, dates, statuses and other available contract fields.</p></div>
        <div><FileText size={19} aria-hidden="true" /><h4>Contract documents</h4><p>Searches indexed document passages for clauses, terms, renewals, fees and notice periods.</p></div>
      </div>
      <p className="help-source-note">Open <strong>Sources</strong> below an answer to review its cited SQL queries and document links. Page references appear when available.</p>
    </section>

    <section className="help-section" aria-labelledby="help-features"><h3 id="help-features">Key features</h3>
      <ul className="help-feature-list">
        <li><MessageCircle size={17} aria-hidden="true" /><span><strong>Ask follow-up questions.</strong> Continue the same topic in a conversation. Start a new chat when changing topics.</span></li>
        <li><BarChart3 size={17} aria-hidden="true" /><span><strong>Explore Genie results.</strong> View tables and switch suitable numeric results to bar or pie charts.</span></li>
        <li><MessageCircle size={17} aria-hidden="true" /><span><strong>Find and organize your work.</strong> Search your conversations, rename or delete chats, and save useful responses.</span></li>
        <li><FileText size={17} aria-hidden="true" /><span><strong>Share feedback.</strong> Rate answers and add editable notes. Thumbs-down requires a note of up to 4,000 characters.</span></li>
      </ul>
    </section>

    <section className="help-section help-limits" aria-labelledby="help-limits"><h3 id="help-limits">Limitations</h3>
      <ul>
        <li>Answers cover the configured contract tables and indexed documents you can access. The app does not search the public web or other systems.</li>
        <li>Results depend on source updates and retrieval coverage. Missing or outdated data can lead to incomplete answers.</li>
        <li>AI can misunderstand a question or produce an incorrect answer. Review the SQL and document evidence before relying on a result.</li>
        <li>Charts require suitable data. Partial results remain table-only; large result sets may be limited.</li>
      </ul>
    </section>

    <div className="help-privacy"><ShieldCheck size={18} aria-hidden="true" /><p>{preview
      ? 'UI preview: answers are demonstrations. Conversations and notes stay in this browser.'
      : `You sign in through Databricks. Data access follows your user permissions, and your chat history is saved ${historyStorage === 'lakebase' ? 'in Lakebase' : 'in the configured local database'} under your account.`}</p></div>
  </div>;
}
