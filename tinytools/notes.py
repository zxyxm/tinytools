"""Transactional local storage for small rich-text notes."""
from datetime import datetime
from pathlib import Path
import sqlite3
from uuid import uuid4


class NoteStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        with self.connection:
            self.connection.execute('''CREATE TABLE IF NOT EXISTS notes (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, html TEXT NOT NULL,
                plain TEXT NOT NULL, updated TEXT NOT NULL, markdown TEXT)''')
            columns = self.connection.execute('PRAGMA table_info(notes)').fetchall()
            if not any(column[1] == 'markdown' for column in columns):
                self.connection.execute('ALTER TABLE notes ADD COLUMN markdown TEXT')

    def list(self):
        return self.connection.execute('SELECT id, title, plain FROM notes ORDER BY updated DESC, rowid DESC').fetchall()

    def get(self, note_id):
        row = self.connection.execute('SELECT title, html FROM notes WHERE id=?', (note_id,)).fetchone()
        if row is None:
            raise KeyError('笔记不存在')
        return row

    def get_markdown(self, note_id):
        return self.connection.execute('SELECT markdown FROM notes WHERE id=?', (note_id,)).fetchone()[0]

    def create(self, title='', html='', plain='', markdown=None):
        note_id = uuid4().hex
        with self.connection:
            self.connection.execute('INSERT INTO notes (id, title, html, plain, updated, markdown) VALUES (?, ?, ?, ?, ?, ?)',
                                    (note_id, title, html, plain, datetime.now().isoformat(), markdown))
        return note_id

    def save(self, note_id, title, html, plain, markdown=None):
        with self.connection:
            cursor = self.connection.execute('UPDATE notes SET title=?, html=?, plain=?, updated=?, markdown=? WHERE id=?',
                                             (title, html, plain, datetime.now().isoformat(), markdown, note_id))
            if cursor.rowcount != 1:
                raise KeyError('笔记不存在，未保存')

    def delete(self, note_id):
        with self.connection:
            self.connection.execute('DELETE FROM notes WHERE id=?', (note_id,))
            row = self.connection.execute('SELECT id FROM notes ORDER BY updated DESC, rowid DESC LIMIT 1').fetchone()
            if row:
                return row[0]
            replacement = uuid4().hex
            self.connection.execute('INSERT INTO notes (id, title, html, plain, updated) VALUES (?, ?, ?, ?, ?)',
                                    (replacement, '', '', '', datetime.now().isoformat()))
            return replacement

    def close(self):
        self.connection.close()
