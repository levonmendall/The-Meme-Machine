"""Complete the reviewed source transformation before candidate freeze.

Acquire the checkpoint generation in the owner FIFO. Fault injection targets the
new real archive queries. Existing reclamation assertions and deadlines remain:
tests wait for safe reset within their original deadline, not at archive commit.
"""
from pathlib import Path
from certification.stagee_coordinated_apply import replace_once

ROOT=Path(__file__).resolve().parents[1]


def apply():
    path=ROOT/'meme_machine/solana_evidence_control.py';text=path.read_text()
    text=replace_once(text,'    def checkpoint_current(self,ticket):\n',
        '    def checkpoint_ticket_after_current(self):\n'
        '        """Issue a marker in FIFO after all older admitted owner work."""\n'
        '        if threading.get_ident()!=self.thread.ident:\n'
        "            raise EvidenceUnavailable('checkpoint_ticket_owner_thread')\n"
        '        with self.cv:\n'
        '            if self.closed or not self._checkpoint_busy:return None\n'
        '            return self._checkpoint_epoch+1\n\n'
        '    def checkpoint_current(self,ticket):\n')
    path.write_text(text)
    path=ROOT/'meme_machine/solana_evidence_service.py';text=path.read_text()
    text=replace_once(text,"'health_scheduler','checkpoint_finish')", "'health_scheduler','checkpoint_prepare','checkpoint_finish')")
    text=replace_once(text,'                ticket=owner.checkpoint_ticket()\n',
        "                ticket=await work(lambda state:owner.checkpoint_ticket_after_current(),2,label='checkpoint_prepare')\n")
    path.write_text(text)
    path=ROOT/'meme_machine/solana_evidence_plane.py';text=path.read_text()
    text=replace_once(text,
        '        The independent PASSIVE connection copies the expensive bulk while source\n'
        '        commits continue. This owner-side TRUNCATE performs only the final\n'
        '        lock/reset handshake between logical writes. A pinned reader must make it\n'
        '        return busy immediately; it may never stall the source owner. The next\n'
        '        bounded checkpoint cycle retries after that reader releases its snapshot.\n',
        '        The service calls this only behind its completed-PASSIVE generation\n'
        '        fence. Without that fence SQLite may copy a newly appended tail;\n'
        '        busy_timeout=0 limits lock waiting, not copying or fsync execution.\n'
        '        Standalone callers retain explicit checkpoint behavior. A pinned\n'
        '        reader returns busy rather than being waited out or invalidated.\n')
    path.write_text(text)
    path=ROOT/'tests/test_run381_retention_progress.py';text=path.read_text()
    text=replace_once(text,"sql.startswith('SELECT scope,slot FROM records')",
        "sql.startswith(('SELECT scope,slot FROM records','SELECT r.identity,c.hash,length(c.body)'))")
    path.write_text(text)
    path=ROOT/'tests/test_run381_maintenance_overlap.py';text=path.read_text()
    text=replace_once(text,'     if len(calls)>=2 and archived==40:break\n',
        '     # Archive publication can invalidate an in-flight checkpoint. The\n'
        '     # existing three-second deadline also covers the next safe reset.\n'
        '     if len(calls)>=2 and archived==40 and finished:break\n')
    text=replace_once(text,"'health_scheduler','checkpoint_finish'})",
        "'health_scheduler','checkpoint_prepare','checkpoint_finish'})")
    path.write_text(text)
    path=ROOT/'certification/build_consistency.py';text=path.read_text()
    text=replace_once(text,"    'tests/test_coordinated_database.py',\n",
        "    'tests/test_coordinated_database.py',\n    'tests/test_run381_retention_progress.py',\n"
        "    'tests/test_run381_maintenance_overlap.py',\n")
    path.write_text(text)
    # The recipe edits the reviewed test contract above. Stage it alongside all
    # other candidate sources in the same authoring commit, before preparation.
    import subprocess
    subprocess.run(['git','add','--','tests/test_run381_maintenance_overlap.py'],cwd=ROOT,check=True)


if __name__=='__main__':apply()
