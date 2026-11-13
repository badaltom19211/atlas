"""Async HTTP boundary: call the exported Python chat() inside this app process."""
import asyncio
import threading
from .notebook_agent import ContractRAGAgent
from .databricks_errors import NotebookCallError


def previous_turn(messages):
    """Notebook chat() remembers one turn; rebuild it from persisted, owned history."""
    last = next((i for i in range(len(messages) - 1, -1, -1) if messages[i]['role'] == 'user'), None)
    if last is None:
        raise ValueError('Missing user question.')
    for i in range(last - 1, -1, -1):
        if messages[i]['role'] == 'assistant':
            question = next((m['content'] for m in reversed(messages[:i]) if m['role'] == 'user'), None)
            if question is not None:
                return messages[last]['content'], {'query': messages[i].get('notebook_query') or question, 'answer': messages[i]['content']}
    return messages[last]['content'], None


class NotebookChatAgent(ContractRAGAgent):
    receipt_name = 'deep_contract_agent'

    def __init__(self, settings, *, token, user_id, conversation_id, glossary=None, tracing=None, slots=None):
        self.settings = settings
        self.token, self.user_id, self.conversation_id = token, user_id, conversation_id
        self.glossary, self.tracing, self.slots = glossary, tracing, slots

    async def answer(self, messages):
        question, previous = previous_turn(messages)
        token = self.token
        if not token and self.settings.auth_mode == 'local':
            from .databricks_client import workspace_client
            headers = await asyncio.to_thread(lambda: workspace_client(self.settings).config.authenticate())
            token = headers.get('Authorization', '').removeprefix('Bearer ')
        if not token:
            raise NotebookCallError('authentication', None)
        last = max(i for i, m in enumerate(messages) if m['role'] == 'user')
        return await self._execute({'token': token, 'user_id': self.user_id,
                                   'session_id': f'{self.user_id}:{self.conversation_id}',
                                   'question': question, 'previous': previous, 'history': messages[:last]})

    async def _execute(self, payload):
        cancel = threading.Event()
        if self.slots is not None:
            await self.slots.acquire()

        def call_chat():
            # Import once per process (Python's module cache); no dynamic exec or subprocess.
            from .deep_agent_v1 import chat
            return chat(payload['question'], token=payload['token'], history=payload['history'],
                        settings=self.settings, user_id=payload['user_id'], session_id=payload['session_id'],
                        glossary=self.glossary, tracing=self.tracing, cancel=cancel)

        task = asyncio.create_task(asyncio.to_thread(call_chat))
        def finished(future):
            # A cancelled HTTP request must not free capacity while sync I/O still runs.
            if self.slots is not None:
                self.slots.release()
            if not future.cancelled():
                future.exception()  # Retrieve failures even when the browser has disconnected.
        task.add_done_callback(finished)
        try:
            result = await asyncio.shield(task)
            return result['answer'], result['custom_outputs']
        except asyncio.CancelledError:
            cancel.set()
            raise
