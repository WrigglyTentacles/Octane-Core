import React, { useState, useEffect, useRef } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from './AuthContext';
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  useDraggable,
  useDroppable,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';

const API = '/api';
const STORAGE_KEY = 'octane-selected-tournament';
const TAB_STORAGE_KEY = 'octane-selected-tab';

/** Convert UTC ISO string to datetime-local value (local timezone). */
function utcToDatetimeLocal(isoStr) {
  if (isoStr == null || isoStr === '') return '';
  const s = String(isoStr).trim();
  if (!s) return '';
  // Treat as UTC if no timezone (Python naive datetime)
  const normalized = s.endsWith('Z') || /[+-]\d{2}:?\d{2}$/.test(s) ? s : s.replace(/\.\d+$/, '') + 'Z';
  const d = new Date(normalized);
  if (isNaN(d.getTime())) return '';
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Get Discord timestamp string from datetime-local value. */
function toDiscordTimestamp(datetimeLocalValue, style = 'R') {
  if (!datetimeLocalValue) return null;
  const ts = Math.floor(new Date(datetimeLocalValue).getTime() / 1000);
  return `<t:${ts}:${style}>`;
}

/** Parse Discord timestamp <t:1234567890:R> or similar, return datetime-local string or null. */
function parseDiscordTimestamp(str) {
  if (!str || typeof str !== 'string') return null;
  const m = str.match(/<t:(\d+):[^>]*>/);
  if (!m) return null;
  const ts = parseInt(m[1], 10);
  if (isNaN(ts)) return null;
  const d = new Date(ts * 1000);
  if (isNaN(d.getTime())) return null;
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

async function parseJson(res) {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(`Server returned ${res.status}: ${text.slice(0, 100)}`);
  }
}

const styles = {
  card: {
    background: 'var(--bg-secondary)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    padding: 16,
    boxShadow: 'var(--shadow)',
  },
  input: {
    flex: 1,
    padding: '10px 14px',
    background: 'var(--bg-tertiary)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-sm)',
    color: 'var(--text-primary)',
  },
  listItem: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '10px 14px',
    background: 'var(--bg-tertiary)',
    borderRadius: 'var(--radius-sm)',
    border: '1px solid var(--border)',
  },
  tab: (active) => ({
    padding: '10px 20px',
    fontWeight: active ? 600 : 500,
    background: active ? 'var(--accent)' : 'var(--bg-tertiary)',
    color: active ? 'var(--bg-primary)' : 'var(--text-secondary)',
    border: '1px solid ' + (active ? 'var(--accent)' : 'var(--border)'),
    borderRadius: 'var(--radius-sm)',
    cursor: 'pointer',
    transition: 'all 0.2s',
  }),
};

function SortableItem({ id, children }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id });
  return (
    <div ref={setNodeRef} style={{ transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.5 : 1 }} {...attributes} {...listeners}>
      {children}
    </div>
  );
}

function EditableList({ title, items, onAdd, onRemove, onReorder, onRename, addPlaceholder, readOnly, canRemoveItem, getItemLabel }) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );
  const [newName, setNewName] = useState('');
  const [editingId, setEditingId] = useState(null);
  const [editValue, setEditValue] = useState('');

  const reorderableItems = canRemoveItem ? items.filter(canRemoveItem) : items;
  const handleDragEnd = (event) => {
    const { active, over } = event;
    if (over && active.id !== over.id) {
      const oldIndex = reorderableItems.findIndex((i) => String(i.id) === String(active.id));
      const newIndex = reorderableItems.findIndex((i) => String(i.id) === String(over.id));
      if (oldIndex !== -1 && newIndex !== -1) {
        onReorder(arrayMove(reorderableItems.map((i) => i.id), oldIndex, newIndex));
      }
    }
  };

  const startEdit = (item) => {
    setEditingId(item.id);
    setEditValue(item.display_name || '');
  };
  const saveEdit = async () => {
    if (editingId == null || !onRename) return;
    const trimmed = editValue.trim();
    if (trimmed) {
      await onRename(editingId, trimmed);
    }
    setEditingId(null);
    setEditValue('');
  };

  return (
    <div style={{ marginBottom: 32 }}>
      <h3 style={{ margin: '0 0 16px', fontSize: 18, color: 'var(--text-primary)' }}>{title}</h3>
      {!readOnly && (
        <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
          <input
            type="text"
            placeholder={addPlaceholder}
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && newName.trim() && (onAdd(newName.trim()), setNewName(''))}
            style={styles.input}
          />
          <button onClick={() => newName.trim() && (onAdd(newName.trim()), setNewName(''))} disabled={!newName.trim()} className="primary">
            Add
          </button>
        </div>
      )}
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={readOnly ? () => {} : handleDragEnd}>
        <SortableContext items={reorderableItems.map((i) => String(i.id))} strategy={verticalListSortingStrategy}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {items.map((item) => {
              const label = getItemLabel ? getItemLabel(item) : item.display_name;
              const removable = canRemoveItem ? canRemoveItem(item) : true;
              const isEditing = editingId === item.id;
              const canRename = onRename && !readOnly;
              const content = (
                <div style={styles.listItem}>
                  {!readOnly && removable && <span style={{ color: 'var(--text-muted)', marginRight: 8 }}>⋮⋮</span>}
                  {isEditing ? (
                    <input
                      type="text"
                      value={editValue}
                      onChange={(e) => setEditValue(e.target.value)}
                      onBlur={saveEdit}
                      onKeyDown={(e) => { if (e.key === 'Enter') saveEdit(); if (e.key === 'Escape') { setEditingId(null); setEditValue(''); } }}
                      autoFocus
                      style={{ ...styles.input, flex: 1, margin: 0, padding: '4px 8px' }}
                    />
                  ) : (
                    <span style={{ flex: 1 }}>{label}</span>
                  )}
                  {!readOnly && !isEditing && (
                    <>
                      {canRename && (
                        <button onClick={() => startEdit(item)} title="Rename" style={{ color: 'var(--text-muted)', background: 'none', border: 'none', cursor: 'pointer', padding: '4px 6px', fontSize: 14 }}>
                          ✎
                        </button>
                      )}
                      {removable && (
                        <button onClick={() => onRemove(item.id)} style={{ color: 'var(--error)', background: 'none', border: 'none', cursor: 'pointer', padding: '4px 8px' }}>
                          Remove
                        </button>
                      )}
                    </>
                  )}
                </div>
              );
              return removable ? (
                <SortableItem key={item.id} id={String(item.id)}>{content}</SortableItem>
              ) : (
                <div key={item.id}>{content}</div>
              );
            })}
          </div>
        </SortableContext>
      </DndContext>
    </div>
  );
}

function RosterItem({ item, prefix, label, onRename, onRemove, onMoveUp, onMoveDown, canRemove, canRename, readOnly }) {
  const id = `${prefix}-${item.id}`;
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({ id });
  const [editing, setEditing] = useState(false);
  const [editVal, setEditVal] = useState(item.display_name || '');

  const saveRename = async () => {
    const t = editVal.trim();
    if (t && onRename) await onRename(item.id, t);
    setEditing(false);
  };

  return (
    <div
      ref={setNodeRef}
      {...(!editing ? { ...attributes, ...listeners } : {})}
      style={{
        ...styles.listItem,
        opacity: isDragging ? 0.5 : 1,
        transform: transform ? `translate3d(${transform.x}px, ${transform.y}px, 0)` : undefined,
      }}
    >
      {editing ? (
        <input
          type="text"
          value={editVal}
          onChange={(e) => setEditVal(e.target.value)}
          onBlur={saveRename}
          onKeyDown={(e) => { if (e.key === 'Enter') saveRename(); if (e.key === 'Escape') setEditing(false); }}
          autoFocus
          onClick={(e) => e.stopPropagation()}
          style={{ ...styles.input, flex: 1, margin: 0, padding: '4px 8px' }}
        />
      ) : (
        <span style={{ flex: 1 }}>{label}</span>
      )}
      {!readOnly && !editing && (
        <>
          {canRename && (
            <button onClick={(e) => { e.stopPropagation(); setEditing(true); setEditVal(item.display_name || ''); }} title="Rename" style={{ color: 'var(--text-muted)', background: 'none', border: 'none', cursor: 'pointer', padding: '4px 6px', fontSize: 14 }}>
              ✎
            </button>
          )}
          {canRemove && (
            <button onClick={(e) => { e.stopPropagation(); onRemove?.(item.id); }} style={{ color: 'var(--error)', background: 'none', border: 'none', cursor: 'pointer', padding: '4px 8px' }}>
              Remove
            </button>
          )}
          {onMoveUp && (
            <button onClick={(e) => { e.stopPropagation(); onMoveUp(item.id); }} title="Move up" style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '2px 4px', fontSize: 12 }}>↑</button>
          )}
          {onMoveDown && (
            <button onClick={(e) => { e.stopPropagation(); onMoveDown(item.id); }} title="Move down" style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '2px 4px', fontSize: 12 }}>↓</button>
          )}
        </>
      )}
    </div>
  );
}

function ParticipantsAndStandbyView({
  participants,
  standby,
  onAddParticipant,
  onAddStandby,
  onRemoveParticipant,
  onRemoveStandby,
  onReorderParticipants,
  onReorderStandby,
  onRenameParticipant,
  onRenameStandby,
  onMoveEntry,
  readOnly,
}) {
  const [newParticipant, setNewParticipant] = useState('');
  const [newStandby, setNewStandby] = useState('');
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  const handleDragEnd = (event) => {
    const { active, over } = event;
    if (!over) return;
    const activeId = String(active.id);
    const overId = String(over.id);
    if (overId === 'zone-standby' && activeId.startsWith('p-')) {
      const rawId = activeId.replace('p-', '');
      const entryId = Number(rawId);
      if (Number.isFinite(entryId) && !rawId.startsWith('discord:')) onMoveEntry?.(entryId, 'standby');
    } else if (overId === 'zone-participants' && activeId.startsWith('s-')) {
      const entryId = Number(activeId.replace('s-', ''));
      const item = standby.find((s) => s.id === entryId);
      if (item?.list_type === 'standby') onMoveEntry?.(entryId, 'participant');
    }
  };

  const moveUp = (list, id, onReorder) => {
    const idx = list.findIndex((i) => i.id === id);
    if (idx <= 0) return;
    const ids = list.map((i) => i.id);
    onReorder(arrayMove(ids, idx, idx - 1));
  };
  const moveDown = (list, id, onReorder) => {
    const idx = list.findIndex((i) => i.id === id);
    if (idx < 0 || idx >= list.length - 1) return;
    const ids = list.map((i) => i.id);
    onReorder(arrayMove(ids, idx, idx + 1));
  };

  return (
    <div style={{ marginBottom: 32 }}>
      <h3 style={{ margin: '0 0 16px', fontSize: 18, color: 'var(--text-primary)' }}>Players — drag between lists to move</h3>
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
          <div>
            <h4 style={{ margin: '0 0 12px', fontSize: 14, color: 'var(--accent)' }}>Participants</h4>
            {!readOnly && (
              <div style={{ display: 'flex', gap: 10, marginBottom: 12 }}>
                <input
                  type="text"
                  placeholder="Display name"
                  value={newParticipant}
                  onChange={(e) => setNewParticipant(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && newParticipant.trim() && (onAddParticipant?.(newParticipant.trim()), setNewParticipant(''))}
                  style={styles.input}
                />
                <button onClick={() => newParticipant.trim() && (onAddParticipant?.(newParticipant.trim()), setNewParticipant(''))} disabled={!newParticipant.trim()} className="primary">Add</button>
              </div>
            )}
            <DroppableZone id="zone-participants" minHeight={80}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {participants.map((item) => {
                  const isDiscord = item.source === 'discord';
                  return (
                    <RosterItem
                      key={item.id}
                      item={item}
                      prefix="p"
                      label={item.display_name + (isDiscord ? ' (Discord)' : '')}
                      onRename={isDiscord ? undefined : onRenameParticipant}
                      onRemove={onRemoveParticipant}
                      onMoveUp={isDiscord ? undefined : (id) => moveUp(participants, id, onReorderParticipants)}
                      onMoveDown={isDiscord ? undefined : (id) => moveDown(participants, id, onReorderParticipants)}
                      canRemove={true}
                      canRename={!isDiscord}
                      readOnly={readOnly}
                    />
                  );
                })}
              </div>
            </DroppableZone>
          </div>
          <div>
            <h4 style={{ margin: '0 0 12px', fontSize: 14, color: 'var(--accent)' }}>Standby / Seat Fillers</h4>
            {!readOnly && (
              <div style={{ display: 'flex', gap: 10, marginBottom: 12 }}>
                <input
                  type="text"
                  placeholder="Display name"
                  value={newStandby}
                  onChange={(e) => setNewStandby(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && newStandby.trim() && (onAddStandby?.(newStandby.trim()), setNewStandby(''))}
                  style={styles.input}
                />
                <button onClick={() => newStandby.trim() && (onAddStandby?.(newStandby.trim()), setNewStandby(''))} disabled={!newStandby.trim()} className="primary">Add</button>
              </div>
            )}
            <DroppableZone id="zone-standby" minHeight={80}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {standby.map((item) => {
                  const inGame = item.original_list_type === 'standby' && item.list_type !== 'standby';
                  return (
                    <RosterItem
                      key={item.id}
                      item={item}
                      prefix="s"
                      label={item.display_name + (inGame ? ' (in game)' : '')}
                      onRename={onRenameStandby}
                      onRemove={inGame ? undefined : onRemoveStandby}
                      onMoveUp={(id) => moveUp(standby, id, onReorderStandby)}
                      onMoveDown={(id) => moveDown(standby, id, onReorderStandby)}
                      canRemove={!inGame}
                      canRename={true}
                      readOnly={readOnly}
                    />
                  );
                })}
              </div>
            </DroppableZone>
          </div>
        </div>
      </DndContext>
    </div>
  );
}

/** Shared tooltip popup - used by TeamSlot and champion/winner displays for consistent hover look */
const tooltipPopupStyle = {
  position: 'absolute',
  left: '50%',
  transform: 'translateX(-50%)',
  bottom: '100%',
  marginBottom: 6,
  padding: '10px 14px',
  background: 'var(--bg-elevated)',
  border: '1px solid var(--border)',
  borderRadius: 'var(--radius-sm)',
  boxShadow: 'var(--shadow)',
  zIndex: 1000,
  minWidth: 140,
  whiteSpace: 'nowrap',
};

function HoverTooltip({ title, items, children }) {
  const [show, setShow] = useState(false);
  const hasContent = items?.length > 0 || title;
  return (
    <div
      style={{ position: 'relative', display: 'inline-block' }}
      onMouseEnter={() => hasContent && setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      <span style={{ cursor: hasContent ? 'help' : 'default' }} title={hasContent ? (items?.length ? `${title}\n${items.join('\n')}` : title) : null}>
        {children}
      </span>
      {show && hasContent && (
        <div style={tooltipPopupStyle}>
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--accent)', marginBottom: 6 }}>{title}</div>
          {items?.map((item, i) => (
            <div key={i} style={{ fontSize: 13, color: 'var(--text-primary)' }}>• {item}</div>
          ))}
        </div>
      )}
    </div>
  );
}

function TeamSlot({ name, teamId, teams, isTeam, title }) {
  const team = isTeam && teams?.length
    ? (teamId ? teams.find((t) => String(t.id) === String(teamId)) : teams.find((t) => t.name === name))
    : null;
  const members = team?.members || [];
  const hasMembers = members.length > 0;
  const items = members.map((m) => m.display_name || m.name || String(m.id));

  if (!hasMembers) {
    return <span>{name || 'TBD'}</span>;
  }
  return (
    <HoverTooltip title={team?.name || name} items={items}>
      {name || 'TBD'}
    </HoverTooltip>
  );
}

function MatchSlot({ label, name, matchId, slot, onDrop, onSwapSlots, onAdvanceOpponent, hasOpponent, teamId, teams, isTeam }) {
  const [isOver, setIsOver] = useState(false);
  const hasContent = name && name !== 'TBD' && name !== 'BYE';
  const canDrag = hasContent && onSwapSlots;
  const slotContent = isTeam && teams?.length ? (
    <TeamSlot name={name} teamId={teamId} teams={teams} isTeam={true} />
  ) : (
    (name || label)
  );
  const handleDrop = (e) => {
    e.preventDefault();
    setIsOver(false);
    const raw = e.dataTransfer.getData('application/json');
    if (!raw) return;
    try {
      const data = JSON.parse(raw);
      if (data?.type === 'bracket_slot' && onSwapSlots && !(data.matchId === matchId && data.slot === slot)) {
        onSwapSlots(data.matchId, data.slot, matchId, slot);
      } else if (onDrop) {
        onDrop(matchId, slot, data);
      }
    } catch {}
  };
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div
        style={{
          flex: 1,
          padding: 14,
          minHeight: 44,
          background: isOver ? 'var(--accent-muted)' : 'var(--bg-tertiary)',
          border: `2px dashed ${isOver ? 'var(--accent)' : 'var(--border)'}`,
          borderRadius: 'var(--radius-sm)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: name && name !== label ? 'var(--text-primary)' : 'var(--text-muted)',
          cursor: canDrag ? 'grab' : 'default',
        }}
        draggable={canDrag}
        onDragStart={(e) => {
          if (!canDrag) return;
          e.dataTransfer.setData('application/json', JSON.stringify({ type: 'bracket_slot', matchId, slot }));
          e.dataTransfer.effectAllowed = 'move';
        }}
        onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; if (onSwapSlots) setIsOver(true); }}
        onDragLeave={(e) => { if (e.currentTarget.contains(e.relatedTarget)) return; setIsOver(false); }}
        onDrop={handleDrop}
      >
        {slotContent}
      </div>
      {name && name !== label && hasOpponent && onAdvanceOpponent && (
        <button
          onClick={() => onAdvanceOpponent(matchId, slot)}
          title="Team dropped out — advance opponent"
          style={{ padding: '6px 10px', fontSize: 11, whiteSpace: 'nowrap' }}
        >
          Advance
        </button>
      )}
    </div>
  );
}

function DraggableEntity({ entity }) {
  return (
    <div
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData('application/json', JSON.stringify({ ...entity, type: 'manual_entry' }));
        e.dataTransfer.effectAllowed = 'move';
      }}
      style={{
        padding: '8px 12px',
        background: 'var(--accent-muted)',
        borderRadius: 'var(--radius-sm)',
        cursor: 'grab',
        border: '1px solid var(--accent)',
        color: 'var(--text-primary)',
      }}
    >
      {entity.display_name || entity.name}
    </div>
  );
}

function DraggablePlayer({ id, name, isStandby }) {
  const playerId = `player-${id}`;
  const { attributes, listeners, setNodeRef: setDragRef, transform, isDragging } = useDraggable({ id: playerId });
  const { setNodeRef: setDropRef, isOver } = useDroppable({ id: playerId });
  const setRefs = (el) => { setDragRef(el); setDropRef(el); };
  return (
    <div
      ref={setRefs}
      {...attributes}
      {...listeners}
      style={{
        padding: '8px 12px',
        background: isOver ? 'rgba(147,233,190,0.25)' : (isStandby ? 'rgba(147,233,190,0.2)' : 'var(--bg-tertiary)'),
        borderRadius: 'var(--radius-sm)',
        border: `1px solid ${isOver ? 'var(--accent)' : 'var(--border)'}`,
        cursor: 'grab',
        opacity: isDragging ? 0.5 : 1,
        transform: transform ? `translate3d(${transform.x}px, ${transform.y}px, 0)` : undefined,
      }}
    >
      {name}{isStandby && <span style={{ marginLeft: 6, fontSize: 11, color: 'var(--text-muted)' }}>(standby)</span>}
    </div>
  );
}

function DroppableZone({ id, children, minHeight = 60 }) {
  const { isOver, setNodeRef } = useDroppable({ id });
  return (
    <div
      ref={setNodeRef}
      style={{
        minHeight,
        padding: 12,
        background: isOver ? 'rgba(147,233,190,0.15)' : 'var(--bg-tertiary)',
        border: `2px dashed ${isOver ? 'var(--accent)' : 'var(--border)'}`,
        borderRadius: 'var(--radius-sm)',
        transition: 'all 0.15s',
      }}
    >
      {children}
    </div>
  );
}

function TeamsView({ teams, participants, standby, onUpdateTeams, onSubstitute, onRegenerate, format, readOnly }) {
  const maxPerTeam = parseInt(format?.split('v')[0]) || 2;
  const allPeople = [...participants.map((p) => ({ ...p, isStandby: false })), ...standby.map((s) => ({ ...s, isStandby: true }))];
  const assignedIds = new Set(teams.flatMap((t) => t.members.map((m) => m.id)));
  const unassigned = allPeople.filter((p) => !assignedIds.has(p.id));

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  const handleDragEnd = (event) => {
    const { active, over } = event;
    if (!over) return;
    const activeId = String(active.id);
    const overId = String(over.id);
    if (!activeId.startsWith('player-')) return;
    const entryId = activeId.replace('player-', '');
    const _sameId = (a, b) => a === b || String(a) === String(b);
    if (overId === 'unassigned') {
      const newTeams = teams.map((t) => ({
        id: t.id,
        name: t.name,
        members: t.members.filter((m) => !_sameId(m.id, entryId)),
      })).filter((t) => t.members.length > 0 || t.id);
      onUpdateTeams(newTeams);
    } else if (overId.startsWith('player-')) {
      const targetId = overId.replace('player-', '');
      if (_sameId(targetId, entryId)) return;
      const person = allPeople.find((p) => _sameId(p.id, entryId));
      const targetPerson = allPeople.find((p) => _sameId(p.id, targetId));
      if (!person || !targetPerson) return;
      const currentTeam = teams.find((t) => t.members.some((m) => _sameId(m.id, entryId)));
      const targetTeam = teams.find((t) => t.members.some((m) => _sameId(m.id, targetId)));
      const newTeams = teams.map((t) => {
        const isCurrent = currentTeam && String(t.id) === String(currentTeam.id);
        const isTarget = targetTeam && String(t.id) === String(targetTeam.id);
        if (isCurrent && isTarget) {
          return { ...t, members: t.members.map((m) => _sameId(m.id, entryId) ? { id: targetPerson.id, display_name: targetPerson.display_name } : _sameId(m.id, targetId) ? { id: person.id, display_name: person.display_name } : m) };
        }
        if (isCurrent) {
          return { ...t, members: t.members.map((m) => _sameId(m.id, entryId) ? { id: targetPerson.id, display_name: targetPerson.display_name } : m) };
        }
        if (isTarget) {
          return { ...t, members: t.members.map((m) => _sameId(m.id, targetId) ? { id: person.id, display_name: person.display_name } : m) };
        }
        return t;
      });
      onUpdateTeams(newTeams);
    } else if (overId.startsWith('team-')) {
      const teamId = overId.replace('team-', '');
      const targetTeam = teams.find((t) => String(t.id) === teamId);
      if (!targetTeam || targetTeam.members.length >= maxPerTeam) return;
      const currentTeam = teams.find((t) => t.members.some((m) => _sameId(m.id, entryId)));
      const person = allPeople.find((p) => _sameId(p.id, entryId));
      if (!person) return;
      let newTeams;
      if (currentTeam) {
        newTeams = teams.map((t) => {
          if (String(t.id) === teamId) {
            if (t.members.some((m) => _sameId(m.id, entryId))) return t;
            return { ...t, members: [...t.members, { id: person.id, display_name: person.display_name }] };
          }
          if (String(t.id) === String(currentTeam.id)) {
            return { ...t, members: t.members.filter((m) => !_sameId(m.id, entryId)) };
          }
          return t;
        });
      } else {
        newTeams = teams.map((t) =>
          String(t.id) === teamId
            ? { ...t, members: [...t.members, { id: person.id, display_name: person.display_name }] }
            : t
        );
      }
      onUpdateTeams(newTeams);
    }
  };

  const handleAddTeam = () => {
    const num = teams.length + 1;
    onUpdateTeams([...teams, { id: `new-${Date.now()}`, name: `Team ${num}`, members: [] }]);
  };

  const handleRemoveTeam = (teamId) => {
    const team = teams.find((t) => String(t.id) === String(teamId));
    if (!team) return;
    onUpdateTeams(teams.filter((t) => String(t.id) !== String(teamId)));
  };

  const handleRenameTeam = (teamId, newName) => {
    onUpdateTeams(
      teams.map((t) => (String(t.id) === String(teamId) ? { ...t, name: newName } : t))
    );
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h3 style={{ margin: 0, color: 'var(--text-primary)' }}>Teams ({format}){readOnly ? '' : ' — Drag to edit'}</h3>
        {!readOnly && (
          <div style={{ display: 'flex', gap: 10 }}>
            <button onClick={handleAddTeam}>Add team</button>
            <button className="primary" onClick={onRegenerate} disabled={allPeople.length < maxPerTeam}>
              Regenerate all
            </button>
          </div>
        )}
      </div>
      <p style={{ color: 'var(--text-secondary)', marginBottom: 20, fontSize: 14 }}>
        {readOnly ? 'View only.' : `Drag players between Unassigned and teams. Max ${maxPerTeam} per team for ${format}. Changes save automatically.`}
      </p>
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={readOnly ? () => {} : handleDragEnd}>
        <div style={{ display: 'grid', gridTemplateColumns: '200px 1fr', gap: 24, alignItems: 'start' }}>
          <div>
            <h4 style={{ margin: '0 0 10px', fontSize: 13, color: 'var(--text-muted)' }}>Unassigned</h4>
            <DroppableZone id="unassigned" minHeight={80}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {unassigned.map((p) => (
                  <DraggablePlayer key={p.id} id={p.id} name={p.display_name} isStandby={p.isStandby} />
                ))}
                {unassigned.length === 0 && (
                  <span style={{ color: 'var(--text-muted)', fontSize: 13 }}>Drop here to remove from team</span>
                )}
              </div>
            </DroppableZone>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16 }}>
            {teams.map((team) => (
              <TeamCard
                key={team.id}
                team={team}
                maxPerTeam={maxPerTeam}
                onRemove={() => handleRemoveTeam(team.id)}
                onRename={(name) => handleRenameTeam(team.id, name)}
                readOnly={readOnly}
              />
            ))}
          </div>
        </div>
      </DndContext>
      {!readOnly && teams.length > 0 && standby.filter((s) => s.list_type === 'standby').length > 0 && (
        <div style={{ ...styles.card, marginTop: 24 }}>
          <h4 style={{ margin: '0 0 12px', color: 'var(--text-primary)' }}>Quick substitute</h4>
          <p style={{ color: 'var(--text-secondary)', margin: 0, fontSize: 13 }}>
            When a player leaves mid-tournament, substitute a standby into their team.
          </p>
          <SubstituteForm teams={teams} standby={standby.filter((s) => s.list_type === 'standby')} onSubstitute={onSubstitute} />
        </div>
      )}
    </div>
  );
}

function TeamCard({ team, maxPerTeam, onRemove, onRename, readOnly }) {
  const [editingName, setEditingName] = useState(false);
  const [nameVal, setNameVal] = useState(team.name);

  return (
    <div style={{ ...styles.card, minWidth: 200, maxWidth: 260 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        {editingName && !readOnly ? (
          <input
            value={nameVal}
            onChange={(e) => setNameVal(e.target.value)}
            onBlur={() => { onRename(nameVal); setEditingName(false); }}
            onKeyDown={(e) => e.key === 'Enter' && (onRename(nameVal), setEditingName(false))}
            style={{ ...styles.input, padding: '6px 10px', flex: 1 }}
            autoFocus
          />
        ) : (
          <h4 style={{ margin: 0, color: 'var(--accent)', cursor: readOnly ? 'default' : 'pointer' }} onClick={() => !readOnly && setEditingName(true)}>
            {team.name}
          </h4>
        )}
        {!readOnly && <button onClick={onRemove} style={{ padding: '4px 8px', fontSize: 12, color: 'var(--error)' }}>×</button>}
      </div>
      <DroppableZone id={`team-${team.id}`} minHeight={44}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {team.members.map((m) => (
            <DraggablePlayer key={m.id} id={m.id} name={m.display_name} isStandby={false} />
          ))}
          {team.members.length < maxPerTeam && (
            <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>Drop here ({team.members.length}/{maxPerTeam})</span>
          )}
        </div>
      </DroppableZone>
    </div>
  );
}

function SubstituteForm({ teams, standby, onSubstitute }) {
  const [teamId, setTeamId] = useState('');
  const [memberId, setMemberId] = useState('');
  const [standbyId, setStandbyId] = useState('');
  const team = teams.find((t) => String(t.id) === String(teamId));
  const members = team?.members ?? [];

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'flex-end', marginTop: 12 }}>
      <div>
        <label style={{ display: 'block', marginBottom: 4, fontSize: 12, color: 'var(--text-muted)' }}>Team</label>
        <select value={teamId} onChange={(e) => { setTeamId(e.target.value); setMemberId(''); }} style={{ padding: '8px 12px', minWidth: 120 }}>
          <option value="">Select</option>
          {teams.map((t) => (
            <option key={t.id} value={t.id}>{t.name}</option>
          ))}
        </select>
      </div>
      <div>
        <label style={{ display: 'block', marginBottom: 4, fontSize: 12, color: 'var(--text-muted)' }}>Leaving</label>
        <select value={memberId} onChange={(e) => setMemberId(e.target.value)} style={{ padding: '8px 12px', minWidth: 120 }} disabled={!teamId}>
          <option value="">Select</option>
          {members.map((m) => (
            <option key={m.id} value={m.id}>{m.display_name}</option>
          ))}
        </select>
      </div>
      <div>
        <label style={{ display: 'block', marginBottom: 4, fontSize: 12, color: 'var(--text-muted)' }}>Standby</label>
        <select value={standbyId} onChange={(e) => setStandbyId(e.target.value)} style={{ padding: '8px 12px', minWidth: 120 }}>
          <option value="">Select</option>
          {standby.map((s) => (
            <option key={s.id} value={s.id}>{s.display_name}</option>
          ))}
        </select>
      </div>
      <button
        className="primary"
        onClick={() => teamId && memberId && standbyId && onSubstitute(Number(teamId), Number(memberId), Number(standbyId))}
        disabled={!teamId || !memberId || !standbyId}
      >
        Substitute
      </button>
    </div>
  );
}

function BracketBox({ name, isWinner, accentSide, teams, teamId, isTeam, isPreview, onDrop, onSwapSlots, matchId, slot, onAdvanceOpponent, onSetWinner, hasOpponent, canSetWinner, canEdit }) {
  const content = isTeam && teams?.length ? (
    <TeamSlot name={name} teamId={teamId} teams={teams} isTeam={true} />
  ) : (
    <span>{name || 'TBD'}</span>
  );
  const hasContent = name && name !== 'TBD' && name !== 'BYE';
  const canDrag = hasContent && onSwapSlots;
  const handleDrop = (e) => {
    e.preventDefault();
    const raw = e.dataTransfer.getData('application/json');
    if (!raw) return;
    try {
      const data = JSON.parse(raw);
      if (data?.type === 'bracket_slot' && onSwapSlots && !(data.matchId === matchId && data.slot === slot)) {
        onSwapSlots(data.matchId, data.slot, matchId, slot);
      } else if (onDrop) {
        onDrop(matchId, slot, data);
      }
    } catch {}
  };
  const boxStyle = {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '10px 14px',
    minWidth: 140,
    minHeight: 40,
    background: 'var(--bg-tertiary)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-sm)',
    color: name && name !== 'TBD' && name !== 'BYE' ? 'var(--text-primary)' : 'var(--text-muted)',
    fontSize: 14,
    fontWeight: isWinner ? 600 : 500,
    borderLeft: accentSide === 'left' ? '4px solid var(--accent)' : undefined,
    borderRight: accentSide === 'right' ? '4px solid var(--accent)' : undefined,
    overflow: 'hidden',
    flexShrink: 0,
  };
  if (isPreview || !onDrop) {
    return (
      <div style={boxStyle} title={typeof name === 'string' ? name : undefined}>
        <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }}>{content}</div>
      </div>
    );
  }
  const canClickWinner = canEdit && canSetWinner && name && name !== 'TBD' && name !== 'BYE' && onSetWinner;
  const isDropout = canEdit && name && name !== 'TBD' && name !== 'BYE' && !hasOpponent && onAdvanceOpponent;
  const showWinnerBtn = canClickWinner || isDropout;
  const handleWinnerClick = () => {
    if (canClickWinner) onSetWinner(matchId, slot);
    else if (isDropout) onAdvanceOpponent(matchId, slot === 1 ? 2 : 1);
  };
  const [isOver, setIsOver] = useState(false);
  const handleDragOver = (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    setIsOver(true);
  };
  const handleDragLeave = (e) => {
    if (e.currentTarget.contains(e.relatedTarget)) return;
    setIsOver(false);
  };
  return (
    <div
      style={{
        ...boxStyle,
        cursor: (canClickWinner || showWinnerBtn) ? 'pointer' : 'default',
        ...(isOver && { background: 'var(--accent-muted)', borderColor: 'var(--accent)' }),
      }}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={(e) => { handleDrop(e); setIsOver(false); }}
      onClick={canClickWinner ? () => onSetWinner(matchId, slot) : undefined}
      title={canClickWinner ? 'Click to set as winner' : (isDropout ? 'Opponent dropped — click to advance winner' : (canDrag ? 'Drag handle to swap with another slot' : (typeof name === 'string' ? name : undefined)))}
    >
      {canDrag && (
        <div
          draggable
          onDragStart={(e) => {
            e.dataTransfer.setData('application/json', JSON.stringify({ type: 'bracket_slot', matchId, slot }));
            e.dataTransfer.effectAllowed = 'move';
          }}
          style={{ cursor: 'grab', padding: '4px 6px', marginRight: 4, color: 'var(--text-muted)', fontSize: 12, flexShrink: 0 }}
          title="Drag to swap with another slot"
          onClick={(e) => e.stopPropagation()}
        >
          ⋮⋮
        </div>
      )}
      <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0, flex: 1 }}>{content}</div>
      {showWinnerBtn && (
        <button onClick={(ev) => { ev.stopPropagation(); handleWinnerClick(); }} style={{ marginLeft: 8, fontSize: 10, padding: '2px 6px', flexShrink: 0 }} title={canClickWinner ? 'Set as winner' : 'Advance winner'}>✓</button>
      )}
    </div>
  );
}

function BracketVisual({ rounds, isTeam, teams, isPreview, onUpdateMatch, onSwapSlots, onAdvanceOpponent, onSetWinner, onSwapWinner, onClearWinner }) {
  const roundEntries = Object.entries(rounds || {}).filter(([k]) => Number(k) < 10).sort((a, b) => Number(a[0]) - Number(b[0]));
  if (roundEntries.length === 0) return <p style={{ color: 'var(--text-muted)', padding: 24 }}>No matches to display.</p>;

  const slotH = 44;
  const matchGap = 24;
  const colW = 180;
  const colGap = 32;

  const lastRoundNum = roundEntries.length > 0 ? roundEntries[roundEntries.length - 1][0] : null;
  const renderMatchBlock = (m, roundNum) => {
    const s1 = m.team1_name || m.player1_name || 'TBD';
    const s2 = m.team2_name || m.player2_name || 'TBD';
    const w1 = m.winner_name === s1;
    const w2 = m.winner_name === s2;
    const bothFilled = (m.team1_id || m.manual_entry1_id || m.player1_id) && (m.team2_id || m.manual_entry2_id || m.player2_id);
    const canSetWinner = bothFilled && !m.winner_name;
    const isChampion = m.winner_name && String(roundNum) === String(lastRoundNum);
    return (
      <div key={m.id} style={{ display: 'flex', flexDirection: 'column', gap: 0, minWidth: colW }}>
        <BracketBox name={s1} isWinner={w1} accentSide="left" teams={teams} teamId={m.team1_id} isTeam={isTeam} isPreview={isPreview} onDrop={onUpdateMatch} onSwapSlots={onSwapSlots} matchId={m.id} slot={1} onAdvanceOpponent={onAdvanceOpponent} onSetWinner={onSetWinner} hasOpponent={!!(m.team2_id || m.manual_entry2_id || m.player2_id)} canSetWinner={canSetWinner} canEdit={!!onUpdateMatch} />
        <div style={{ height: 1, background: 'var(--border)', margin: '2px 0' }} />
        <BracketBox name={s2} isWinner={w2} accentSide="left" teams={teams} teamId={m.team2_id} isTeam={isTeam} isPreview={isPreview} onDrop={onUpdateMatch} onSwapSlots={onSwapSlots} matchId={m.id} slot={2} onAdvanceOpponent={onAdvanceOpponent} onSetWinner={onSetWinner} hasOpponent={!!(m.team1_id || m.manual_entry1_id || m.player1_id)} canSetWinner={canSetWinner} canEdit={!!onUpdateMatch} />
        {m.winner_name && (
          isChampion ? (
            <div className="grand-final-winners-zone" style={{ overflow: 'visible' }}>
              <span className="champion-label">👑 Tournament Champion</span>
              <span className="champion-name">
                {isTeam && teams?.length && m.winner_team_id ? (
                  <TeamSlot name={m.winner_name} teamId={m.winner_team_id} teams={teams} isTeam={true} />
                ) : (
                  <HoverTooltip title="Champion" items={[m.winner_name]}>{m.winner_name}</HoverTooltip>
                )}
              </span>
              {!m.inferred_winner && (onSwapWinner || onClearWinner) && bothFilled && (
                <div style={{ marginTop: 10, display: 'flex', justifyContent: 'center', gap: 8 }}>
                  {onSwapWinner && <button onClick={() => onSwapWinner(m.id)} style={{ fontSize: 10, padding: '2px 6px' }} title="Swap winner">Swap</button>}
                  {onClearWinner && <button onClick={() => onClearWinner(m.id)} style={{ fontSize: 10, padding: '2px 6px', color: 'var(--text-muted)' }} title="Undo winner">Undo</button>}
                </div>
              )}
            </div>
          ) : (
            <div className="winners-zone" style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 12, color: 'var(--success)', fontWeight: 600 }}>🏆 {m.winner_name}</span>
              {m.inferred_winner && <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>(advanced)</span>}
              {!m.inferred_winner && onSwapWinner && bothFilled && (
                <button onClick={() => onSwapWinner(m.id)} style={{ fontSize: 10, padding: '2px 6px' }} title="Swap winner (wrong result reported)">
                  Swap
                </button>
              )}
              {!m.inferred_winner && onClearWinner && bothFilled && (
                <button onClick={() => onClearWinner(m.id)} style={{ fontSize: 10, padding: '2px 6px', color: 'var(--text-muted)' }} title="Undo winner (clear and fix manually)">
                  Undo
                </button>
              )}
            </div>
          )
        )}
        {canSetWinner && onSetWinner && (
          <div style={{ marginTop: 4, fontSize: 10, color: 'var(--text-muted)' }}>Click team to set winner</div>
        )}
      </div>
    );
  };

  // Vertical column layout: Round 1 → Round 2 → ... → Final
  // Each match: team1 | team2, winner advances to next round
  return (
    <div style={{ overflow: 'auto', maxHeight: 'min(70vh, 560px)', padding: 24, borderRadius: 'var(--radius)', border: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', gap: colGap, minWidth: 'min-content', alignItems: 'flex-start' }}>
        {roundEntries.map(([roundNum, matches]) => (
          <div key={roundNum} style={{ display: 'flex', flexDirection: 'column', gap: matchGap, alignItems: 'flex-start' }}>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6, fontWeight: 600 }}>Round {roundNum}</div>
            {matches.map((m) => m && renderMatchBlock(m, roundNum))}
          </div>
        ))}
      </div>
    </div>
  );
}

function BracketTree({ rounds, isTeam, teams, isPreview, onUpdateMatch, onSwapSlots, onAdvanceOpponent, onSwapWinner, onClearWinner }) {
  const roundEntries = Object.entries(rounds || {}).filter(([k]) => Number(k) < 10).sort((a, b) => Number(a[0]) - Number(b[0]));
  if (roundEntries.length === 0) return <p style={{ color: 'var(--text-muted)', padding: 24 }}>No matches to display.</p>;

  const firstRoundMatches = roundEntries[0][1].length;
  const totalRows = Math.max(firstRoundMatches * 2, 4);
  const rowHeight = 70;

  const renderSlot = (m, slot, s, teamId) => (
    <div
      key={slot}
      style={{
        padding: '8px 12px',
        background: 'var(--bg-tertiary)',
        borderRadius: 'var(--radius-sm)',
        fontSize: 13,
        color: s && s !== 'TBD' ? 'var(--text-primary)' : 'var(--text-muted)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: 36,
      }}
    >
      {isTeam && teams?.length ? (
        <TeamSlot name={s} teamId={teamId} teams={teams} isTeam={true} />
      ) : (
        <span>{s || 'TBD'}</span>
      )}
    </div>
  );

  const renderMatch = (m, rowSpan, colIdx) => {
    const s1 = m.team1_name || m.player1_name || 'TBD';
    const s2 = m.team2_name || m.player2_name || 'TBD';
    const isEditable = !isPreview && onUpdateMatch;
    return (
      <div
        key={m.id}
        style={{
          gridRow: `span ${rowSpan}`,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          minHeight: rowSpan * 52,
        }}
      >
        <div
          style={{
            ...styles.card,
            padding: 12,
            border: '1px solid var(--border)',
            position: 'relative',
          }}
        >
          {isEditable ? (
            <>
              <MatchSlot label="Slot 1" name={s1} matchId={m.id} slot={1} onDrop={onUpdateMatch} onSwapSlots={onSwapSlots} onAdvanceOpponent={onAdvanceOpponent} hasOpponent={!!(m.team2_id || m.manual_entry2_id || m.player2_id)} teamId={m.team1_id} teams={teams} isTeam={isTeam} />
              <span style={{ display: 'block', textAlign: 'center', color: 'var(--text-muted)', fontSize: 11, margin: '4px 0' }}>vs</span>
              <MatchSlot label="Slot 2" name={s2} matchId={m.id} slot={2} onDrop={onUpdateMatch} onSwapSlots={onSwapSlots} onAdvanceOpponent={onAdvanceOpponent} hasOpponent={!!(m.team1_id || m.manual_entry1_id || m.player1_id)} teamId={m.team2_id} teams={teams} isTeam={isTeam} />
            </>
          ) : (
            <>
              {renderSlot(m, 1, s1, m.team1_id)}
              <span style={{ display: 'block', textAlign: 'center', color: 'var(--text-muted)', fontSize: 11, margin: '4px 0' }}>vs</span>
              {renderSlot(m, 2, s2, m.team2_id)}
            </>
          )}
          {m.winner_name && (
            <div className="winners-zone" style={{ marginTop: 6, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 12, color: 'var(--success)', fontWeight: 600 }}>
                🏆 {isTeam && teams?.length && m.winner_team_id ? (
                  <TeamSlot name={m.winner_name} teamId={m.winner_team_id} teams={teams} isTeam={true} />
                ) : (
                  <HoverTooltip title="Winner" items={[m.winner_name]}>{m.winner_name}</HoverTooltip>
                )}
              </span>
              {m.inferred_winner && <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>(advanced)</span>}
              {!m.inferred_winner && onSwapWinner && (m.team1_id || m.manual_entry1_id || m.player1_id) && (m.team2_id || m.manual_entry2_id || m.player2_id) && (
                <button onClick={() => onSwapWinner(m.id)} style={{ fontSize: 10, padding: '2px 6px' }} title="Swap winner (wrong result reported)">
                  Swap
                </button>
              )}
              {!m.inferred_winner && onClearWinner && (m.team1_id || m.manual_entry1_id || m.player1_id) && (m.team2_id || m.manual_entry2_id || m.player2_id) && (
                <button onClick={() => onClearWinner(m.id)} style={{ fontSize: 10, padding: '2px 6px', color: 'var(--text-muted)' }} title="Undo winner (clear and fix manually)">
                  Undo
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    );
  };

  const cols = roundEntries.length;
  const rows = totalRows;
  const gridStyle = {
    display: 'grid',
    gridTemplateColumns: roundEntries.map(() => 'minmax(220px, 1fr)').join(' '),
    gridTemplateRows: `repeat(${rows}, ${rowHeight}px)`,
    gap: '0 24px',
    alignItems: 'center',
    position: 'relative',
  };

  const cells = [];
  roundEntries.forEach(([roundNum, matches], colIdx) => {
    const rowSpan = Math.max(1, Math.floor(rows / matches.length));
    matches.forEach((m, i) => {
      const r = i * rowSpan;
      cells.push(
        <div
          key={`${roundNum}-${m.id}`}
          style={{
            gridColumn: colIdx + 1,
            gridRow: `${r + 1} / span ${rowSpan}`,
            display: 'flex',
            alignItems: 'center',
            minHeight: rowSpan * rowHeight,
          }}
        >
          <div style={{ width: '100%' }}>{renderMatch(m, rowSpan, colIdx)}</div>
        </div>
      );
    });
  });

  return (
    <div style={{ overflowX: 'auto', paddingBottom: 24, minHeight: 200 }}>
      <div style={{ ...gridStyle, minWidth: cols * 240, padding: 16 }}>
        {cells}
      </div>
      <div style={{ display: 'flex', gap: 24, marginTop: 12, fontSize: 12, color: 'var(--text-muted)' }}>
        {roundEntries.map(([r], i) => (
          <span key={r}>
            Round {r}{i < roundEntries.length - 1 ? ' →' : ''}
          </span>
        ))}
      </div>
    </div>
  );
}

/** Infer winner from advancement: if a team was dragged to the next round, they won their previous match. */
function enrichRoundsWithInferredWinners(rounds) {
  if (!rounds || typeof rounds !== 'object') return rounds;
  const allMatches = Object.values(rounds).flat();
  const byId = Object.fromEntries(allMatches.map((m) => [m.id, m]));
  const enriched = {};
  for (const [r, matches] of Object.entries(rounds)) {
    enriched[r] = matches.map((m) => {
      const copy = { ...m };
      if (!copy.winner_name && copy.parent_match_id) {
        const parent = byId[copy.parent_match_id];
        if (parent) {
          const slot = copy.parent_match_slot;
          const advancedName = slot === 1 ? (parent.team1_name || parent.player1_name) : (parent.team2_name || parent.player2_name);
          if (advancedName && advancedName !== 'TBD' && advancedName !== 'BYE') {
            copy.winner_name = advancedName;
            copy.inferred_winner = true;
          }
        }
      }
      return copy;
    });
  }
  return enriched;
}

function BracketView({ bracket, tournament, teams, participants, standby, onUpdateMatch, onAdvanceOpponent, onSetWinner, onSwapWinner, onClearWinner, onSwapSlots, isPreview, canEdit }) {
  const isTeam = tournament?.format !== '1v1';
  const teamsToUse = (bracket?.teams && bracket.teams.length > 0) ? bracket.teams : (teams || []);

  const rawRounds = bracket?.rounds || {};
  const rounds = enrichRoundsWithInferredWinners(rawRounds);
  const allMatches = Object.values(rounds).flat();
  const isDoubleElim = bracket?.bracket_type === 'double_elim';

  const bySection = isDoubleElim
    ? {
        winners: allMatches.filter((m) => (m.bracket_section || 'winners') === 'winners'),
        losers: allMatches.filter((m) => m.bracket_section === 'losers'),
        grand_finals: allMatches.filter((m) => m.bracket_section === 'grand_finals'),
      }
    : null;

  const renderRound = (roundNum, matches, sectionLabel) => {
    const displayRound = sectionLabel === 'Losers' && roundNum >= 10 ? roundNum - 10 : roundNum;
    return (
    <div key={(sectionLabel || '') + roundNum} style={{ minWidth: 280 }}>
      <h4 style={{ margin: '0 0 12px', color: 'var(--accent)', fontSize: 14, fontWeight: 600 }}>
        {sectionLabel ? `${sectionLabel} — ` : ''}Round {displayRound}
      </h4>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {matches.map((m) => {
          const s1 = m.team1_name || m.player1_name || 'TBD';
          const s2 = m.team2_name || m.player2_name || 'TBD';
          const hasOpponent = (m.team1_id || m.manual_entry1_id || m.player1_id) && (m.team2_id || m.manual_entry2_id || m.player2_id);
          return (
            <div key={m.id} style={{ ...styles.card, padding: 16 }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {isPreview ? (
                  <>
                    <div style={{ padding: 14, background: 'var(--bg-tertiary)', borderRadius: 'var(--radius-sm)', color: s1 && s1 !== 'TBD' ? 'var(--text-primary)' : 'var(--text-muted)' }}>
                      {isTeam && teamsToUse?.length ? <TeamSlot name={s1} teamId={m.team1_id} teams={teamsToUse} isTeam={true} /> : (s1 || 'Slot 1')}
                    </div>
                    <span style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>vs</span>
                    <div style={{ padding: 14, background: 'var(--bg-tertiary)', borderRadius: 'var(--radius-sm)', color: s2 && s2 !== 'TBD' ? 'var(--text-primary)' : 'var(--text-muted)' }}>
                      {isTeam && teamsToUse?.length ? <TeamSlot name={s2} teamId={m.team2_id} teams={teamsToUse} isTeam={true} /> : (s2 || 'Slot 2')}
                    </div>
                  </>
                ) : (
                  <>
                <MatchSlot label="Slot 1" name={s1} matchId={m.id} slot={1} onDrop={canEdit ? onUpdateMatch : null} onSwapSlots={canEdit ? onSwapSlots : null} onAdvanceOpponent={canEdit ? onAdvanceOpponent : null} hasOpponent={!!(m.team2_id || m.manual_entry2_id || m.player2_id)} teamId={m.team1_id} teams={teamsToUse} isTeam={isTeam} />
                <span style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>vs</span>
                <MatchSlot label="Slot 2" name={s2} matchId={m.id} slot={2} onDrop={canEdit ? onUpdateMatch : null} onSwapSlots={canEdit ? onSwapSlots : null} onAdvanceOpponent={canEdit ? onAdvanceOpponent : null} hasOpponent={!!(m.team1_id || m.manual_entry1_id || m.player1_id)} teamId={m.team2_id} teams={teamsToUse} isTeam={isTeam} />
                  </>
                )}
                {m.winner_name && (
                  sectionLabel === 'Grand Finals' ? (
                    <div className="grand-final-winners-zone" style={{ overflow: 'visible' }}>
                      <span className="champion-label">👑 Tournament Champion</span>
                      <span className="champion-name">
                        {isTeam && teamsToUse?.length && m.winner_team_id ? (
                          <TeamSlot name={m.winner_name} teamId={m.winner_team_id} teams={teamsToUse} isTeam={true} />
                        ) : (
                          <HoverTooltip title="Champion" items={[m.winner_name]}>{m.winner_name}</HoverTooltip>
                        )}
                      </span>
                      {!m.inferred_winner && canEdit && hasOpponent && (
                        <div style={{ marginTop: 10, display: 'flex', justifyContent: 'center', gap: 8 }}>
                          <button onClick={() => onSwapWinner(m.id)} style={{ fontSize: 11, padding: '4px 8px' }} title="Swap winner">
                            Swap
                          </button>
                          <button onClick={() => onClearWinner(m.id)} style={{ fontSize: 11, padding: '4px 8px', color: 'var(--text-muted)' }} title="Undo winner">
                            Undo
                          </button>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="winners-zone" style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                      <span style={{ color: 'var(--success)', fontWeight: 600, fontSize: 14 }}>
                        🏆 Winner: {isTeam && teamsToUse?.length && m.winner_team_id ? (
                          <TeamSlot name={m.winner_name} teamId={m.winner_team_id} teams={teamsToUse} isTeam={true} />
                        ) : (
                          <HoverTooltip title="Winner" items={[m.winner_name]}>{m.winner_name}</HoverTooltip>
                        )}
                      </span>
                      {m.inferred_winner && <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>(advanced)</span>}
                      {!m.inferred_winner && canEdit && onSwapWinner && hasOpponent && (
                        <button onClick={() => onSwapWinner(m.id)} style={{ fontSize: 11, padding: '4px 8px' }} title="Swap winner (wrong result reported)">
                          Swap
                        </button>
                      )}
                      {!m.inferred_winner && canEdit && onClearWinner && hasOpponent && (
                        <button onClick={() => onClearWinner(m.id)} style={{ fontSize: 11, padding: '4px 8px', color: 'var(--text-muted)' }} title="Undo winner (clear and fix manually)">
                          Undo
                        </button>
                      )}
                    </div>
                  )
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
  };

  const renderSingleElimTree = () => {
    const roundsArr = Object.entries(rounds).filter(([k]) => Number(k) < 10).sort((a, b) => Number(a[0]) - Number(b[0]));
    const roundsObj = Object.fromEntries(roundsArr);
    return (
        <BracketVisual
        rounds={roundsObj}
        isTeam={isTeam}
        teams={teamsToUse}
        isPreview={isPreview}
        onUpdateMatch={canEdit ? onUpdateMatch : null}
        onSwapSlots={canEdit ? onSwapSlots : null}
        onAdvanceOpponent={canEdit ? onAdvanceOpponent : null}
        onSetWinner={canEdit ? onSetWinner : null}
        onSwapWinner={canEdit ? onSwapWinner : null}
        onClearWinner={canEdit ? onClearWinner : null}
      />
    );
  };

  const renderBracket = () => {
    if (isDoubleElim && bySection) {
      const wByRound = {};
      bySection.winners.forEach((m) => { wByRound[m.round_num] = (wByRound[m.round_num] || []).concat(m); });
      const lByRound = {};
      bySection.losers.forEach((m) => { lByRound[m.round_num] = (lByRound[m.round_num] || []).concat(m); });
      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 32 }}>
          <div>
            <h3 style={{ margin: '0 0 16px', color: 'var(--accent)', fontSize: 16 }}>Winners Bracket</h3>
            <BracketTree rounds={Object.fromEntries(Object.entries(wByRound).sort((a, b) => a[0] - b[0]))} isTeam={isTeam} teams={teamsToUse} isPreview={isPreview} onUpdateMatch={onUpdateMatch} onSwapSlots={onSwapSlots} onAdvanceOpponent={onAdvanceOpponent} onSwapWinner={onSwapWinner} onClearWinner={onClearWinner} />
          </div>
          <div style={{ borderTop: '1px solid var(--border)', paddingTop: 24 }}>
            <h3 style={{ margin: '0 0 16px', color: 'var(--accent)', fontSize: 16 }}>Losers Bracket</h3>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24 }}>
              {Object.entries(lByRound).sort((a, b) => a[0] - b[0]).map(([r, ms]) => renderRound(Number(r), ms, 'Losers'))}
            </div>
          </div>
          {bySection.grand_finals.length > 0 && (
            <div style={{ borderTop: '1px solid var(--border)', paddingTop: 24 }}>
              {renderRound(21, bySection.grand_finals, 'Grand Finals')}
            </div>
          )}
        </div>
      );
    }
    return renderSingleElimTree();
  };

  return (
    <div style={{ marginTop: 24 }}>
      <div style={{ minWidth: 0 }}>
        <h2 style={{ margin: '0 0 20px', fontSize: 22, color: 'var(--text-primary)' }}>
          {bracket?.tournament?.name} — {isPreview ? 'Preview' : 'Bracket'} {isDoubleElim && '(Double Elim)'}
        </h2>
        {isTeam && teamsToUse?.length > 0 && (
          <p style={{ color: 'var(--text-muted)', fontSize: 13, marginBottom: 16 }}>
            Hover over a team name to see members.
          </p>
        )}
        {renderBracket()}
      </div>
    </div>
  );
}

function App() {
  const { canEdit, authFetch, user, logout, isAdmin, loading: authLoading } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [siteTitle, setSiteTitle] = useState('Octane Bracket Manager');
  const [tournaments, setTournaments] = useState([]);
  const [tournamentId, setTournamentIdState] = useState(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      return saved ? Number(saved) : null;
    } catch {
      return null;
    }
  });
  const setTournamentId = (id) => {
    setTournamentIdState(id);
    try {
      if (id != null) localStorage.setItem(STORAGE_KEY, String(id));
      else localStorage.removeItem(STORAGE_KEY);
    } catch {}
  };
  const [participants, setParticipants] = useState([]);
  const [standby, setStandby] = useState([]);
  const [teams, setTeams] = useState([]);
  const [bracket, setBracket] = useState(null);
  const [previewBracket, setPreviewBracket] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('players');
  const [newTournamentName, setNewTournamentName] = useState('');
  const [newTournamentFormat, setNewTournamentFormat] = useState('1v1');
  const [newTournamentDeadline, setNewTournamentDeadline] = useState('');
  const [bracketType, setBracketType] = useState('single_elim');
  const [renameValue, setRenameValue] = useState('');
  const [deadlineValue, setDeadlineValue] = useState('');
  const [copyFeedback, setCopyFeedback] = useState(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [menuSection, setMenuSection] = useState(null); // null | 'rename' | 'create' | 'deadline'
  const [showArchived, setShowArchived] = useState(false);
  const [discordConfigReady, setDiscordConfigReady] = useState(false);

  const fetchTournaments = async (includeArchived = showArchived) => {
    try {
      const res = await authFetch(`${API}/tournaments${includeArchived ? '?include_archived=1' : ''}`);
      const data = await parseJson(res);
      const list = Array.isArray(data) ? data : [];
      setTournaments(list);
      if (list.length) {
        const saved = (() => { try { const s = localStorage.getItem(STORAGE_KEY); return s ? Number(s) : null; } catch { return null; } })();
        const valid = saved && list.some((t) => t.id === saved);
        if (valid) setTournamentId(saved);
        else setTournamentId(list[0].id);
      }
      return list;
    } catch (err) {
      setError(err.message);
      return [];
    }
  };

  const fetchData = async (options = {}) => {
    if (!tournamentId) return;
    const silent = options.silent === true;
    if (!silent) setLoading(true);
    setError(null);
    try {
      const [pRes, sRes, bRes, tRes] = await Promise.all([
        authFetch(`${API}/tournaments/${tournamentId}/participants`),
        authFetch(`${API}/tournaments/${tournamentId}/standby`),
        authFetch(`${API}/tournaments/${tournamentId}/bracket`),
        authFetch(`${API}/tournaments/${tournamentId}/teams`),
      ]);
      const pData = await parseJson(pRes);
      const sData = await parseJson(sRes);
      const tData = await parseJson(tRes);
      let bData = null;
      if (bRes.ok) {
        bData = await parseJson(bRes);
        if (bData?.error) bData = null;
      } else if (bRes.status !== 404) {
        bData = { error: (await parseJson(bRes))?.detail || 'Failed to load' };
      }
      setParticipants(Array.isArray(pData) ? pData : []);
      setStandby(Array.isArray(sData) ? sData : []);
      setTeams(Array.isArray(tData) ? tData : []);
      setBracket(bData);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!menuOpen) return;
    fetch(`${API}/settings/discord`).then((r) => r.ok ? r.json() : {}).then((d) => {
      setDiscordConfigReady(!!(d?.enabled && d?.discord_guild_id && d?.discord_signup_channel_id));
    }).catch(() => setDiscordConfigReady(false));
  }, [menuOpen]);

  useEffect(() => {
    fetch(`${API}/settings`).then((r) => r.text()).then((text) => {
      let s = {};
      try {
        s = text ? JSON.parse(text) : {};
      } catch {
        return;
      }
      setSiteTitle(s.site_title || 'Octane Bracket Manager');
      if (s.accent_color) document.documentElement.style.setProperty('--accent', s.accent_color);
      if (s.accent_hover) document.documentElement.style.setProperty('--accent-hover', s.accent_hover);
      if (s.bg_primary) document.documentElement.style.setProperty('--bg-primary', s.bg_primary);
      if (s.bg_secondary) document.documentElement.style.setProperty('--bg-secondary', s.bg_secondary);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!authLoading && !user) {
      navigate('/login', { replace: true, state: { from: location } });
    }
  }, [authLoading, user, navigate, location]);

  useEffect(() => {
    fetchTournaments();
  }, []);

  useEffect(() => {
    fetchData();
  }, [tournamentId]);

  // Restore last tab on initial load when landing at /
  const hasRestoredTab = useRef(false);
  useEffect(() => {
    if (hasRestoredTab.current || location.pathname !== '/') return;
    if (!tournaments.length) return;
    try {
      const saved = localStorage.getItem(TAB_STORAGE_KEY);
      if (saved === 'bracket') {
        hasRestoredTab.current = true;
        navigate('/bracket', { replace: true });
      } else if (saved === 'teams') {
        const fmt = tournaments.find((t) => t.id === tournamentId)?.format;
        if (fmt && fmt !== '1v1') {
          hasRestoredTab.current = true;
          navigate('/teams', { replace: true });
        }
      }
    } catch {}
  }, [tournaments, tournamentId, location.pathname, navigate]);

  // Sync activeTab with URL path so /teams, /bracket, etc. work
  useEffect(() => {
    const path = location.pathname;
    if (path === '/participants' || path === '/standby') {
      navigate('/', { replace: true });
      return;
    }
    const tabFromPath = path === '/' ? 'players' : path.slice(1);
    const validTabs = ['players', 'teams', 'bracket'];
    if (validTabs.includes(tabFromPath)) {
      const fmt = tournaments.find((t) => t.id === tournamentId)?.format;
      const isTeamFormat = fmt && fmt !== '1v1';
      const knowFormat = tournaments.length && tournamentId && fmt;
      if (tabFromPath === 'teams' && knowFormat && !isTeamFormat) {
        navigate('/', { replace: true });
      } else {
        setActiveTab(tabFromPath);
        try {
          localStorage.setItem(TAB_STORAGE_KEY, tabFromPath);
        } catch {}
      }
    }
  }, [location.pathname, tournamentId, tournaments, navigate]);

  const fetchPreview = async () => {
    if (!tournamentId) return;
    const fmt = tournaments.find((t) => t.id === tournamentId)?.format;
    const hasData = fmt === '1v1' ? participants.length >= 2 : teams.length >= 2;
    if (!hasData) return;
    try {
      const res = await authFetch(`${API}/tournaments/${tournamentId}/bracket/preview?bracket_type=${bracketType}`);
      const data = await parseJson(res);
      if (res.ok && !data.error) setPreviewBracket(data);
      else setPreviewBracket(null);
    } catch {
      setPreviewBracket(null);
    }
  };

  useEffect(() => {
    const hasBracket = bracket && Object.keys(bracket.rounds || {}).length > 0;
    const fmt = tournaments.find((t) => t.id === tournamentId)?.format;
    const hasData = fmt === '1v1' ? participants.length >= 2 : teams.length >= 2;
    if (activeTab === 'bracket' && !hasBracket && hasData) fetchPreview();
    else setPreviewBracket(null);
  }, [activeTab, tournamentId, bracket, bracketType, participants.length, teams.length, tournaments]);

  const addParticipant = async (displayName) => {
    try {
      const res = await authFetch(`${API}/tournaments/${tournamentId}/participants`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ display_name: displayName }),
      });
      const data = await parseJson(res);
      if (!res.ok) throw new Error(data?.detail || 'Request failed');
      await fetchData({ silent: true });
    } catch (err) {
      setError(err.message);
    }
  };

  const removeParticipant = async (id) => {
    try {
      if (typeof id === 'string' && id.startsWith('discord:')) {
        const playerId = id.replace('discord:', '');
        await authFetch(`${API}/tournaments/${tournamentId}/registrations/${playerId}`, { method: 'DELETE' });
      } else {
        await authFetch(`${API}/tournaments/${tournamentId}/participants/${id}`, { method: 'DELETE' });
      }
      await fetchData({ silent: true });
    } catch (err) {
      setError(err.message);
    }
  };

  const reorderParticipants = async (entryIds) => {
    try {
      const manualIds = entryIds.filter((id) => typeof id === 'number');
      await authFetch(`${API}/tournaments/${tournamentId}/participants/reorder`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ entry_ids: manualIds }),
      });
      await fetchData({ silent: true });
    } catch (err) {
      setError(err.message);
    }
  };

  const renameParticipant = async (entryId, displayName) => {
    try {
      await authFetch(`${API}/tournaments/${tournamentId}/participants/${entryId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ display_name: displayName }),
      });
      await fetchData({ silent: true });
    } catch (err) {
      setError(err.message);
    }
  };

  const addStandby = async (displayName) => {
    try {
      const res = await authFetch(`${API}/tournaments/${tournamentId}/standby`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ display_name: displayName }),
      });
      const data = await parseJson(res);
      if (!res.ok) throw new Error(data?.detail || 'Request failed');
      await fetchData({ silent: true });
    } catch (err) {
      setError(err.message);
    }
  };

  const removeStandby = async (id) => {
    try {
      await authFetch(`${API}/tournaments/${tournamentId}/standby/${id}`, { method: 'DELETE' });
      await fetchData({ silent: true });
    } catch (err) {
      setError(err.message);
    }
  };

  const reorderStandby = async (entryIds) => {
    try {
      await authFetch(`${API}/tournaments/${tournamentId}/standby/reorder`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ entry_ids: entryIds }),
      });
      await fetchData({ silent: true });
    } catch (err) {
      setError(err.message);
    }
  };

  const renameStandby = async (entryId, displayName) => {
    try {
      await authFetch(`${API}/tournaments/${tournamentId}/standby/${entryId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ display_name: displayName }),
      });
      await fetchData({ silent: true });
    } catch (err) {
      setError(err.message);
    }
  };

  const moveEntry = async (entryId, listType) => {
    try {
      await authFetch(`${API}/tournaments/${tournamentId}/manual-entries/${entryId}/move`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ list_type: listType }),
      });
      await fetchData({ silent: true });
    } catch (err) {
      setError(err.message);
    }
  };

  const updateMatch = async (matchId, slot, entity) => {
    if (!entity) return;
    let body;
    if (entity.type === 'team') {
      body = slot === 1 ? { team1_id: entity.id } : { team2_id: entity.id };
    } else if (entity.type === 'manual_entry') {
      body = slot === 1 ? { manual_entry1_id: entity.id } : { manual_entry2_id: entity.id };
    } else return;
    try {
      const res = await authFetch(`${API}/tournaments/${tournamentId}/bracket/matches/${matchId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error('Failed to update');
      await fetchData({ silent: true });
    } catch (err) {
      setError(err.message);
    }
  };

  const clearWinner = async (matchId) => {
    try {
      const res = await authFetch(`${API}/tournaments/${tournamentId}/bracket/matches/${matchId}/clear-winner`, {
        method: 'POST',
      });
      if (!res.ok) {
        const data = await parseJson(res);
        throw new Error(data?.detail || 'Failed to clear winner');
      }
      await fetchData({ silent: true });
    } catch (err) {
      setError(err.message);
    }
  };

  const swapSlots = async (fromMatchId, fromSlot, toMatchId, toSlot) => {
    if (fromMatchId === toMatchId && fromSlot === toSlot) return;
    try {
      const res = await authFetch(`${API}/tournaments/${tournamentId}/bracket/matches/swap-slots`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ from_match_id: fromMatchId, from_slot: fromSlot, to_match_id: toMatchId, to_slot: toSlot }),
      });
      if (!res.ok) {
        const data = await parseJson(res);
        throw new Error(data?.detail || 'Failed to swap');
      }
      await fetchData({ silent: true });
    } catch (err) {
      setError(err.message);
    }
  };

  const swapWinner = async (matchId) => {
    try {
      const res = await authFetch(`${API}/tournaments/${tournamentId}/bracket/matches/${matchId}/swap-winner`, {
        method: 'POST',
      });
      if (!res.ok) {
        const data = await parseJson(res);
        throw new Error(data?.detail || 'Failed to swap winner');
      }
      await fetchData({ silent: true });
    } catch (err) {
      setError(err.message);
    }
  };

  const setWinner = async (matchId, slot) => {
    const m = bracket?.rounds && Object.values(bracket.rounds).flat().find((x) => x.id === matchId);
    if (!m) return;
    const isTeam = bracket?.tournament?.format !== '1v1';
    const winnerId = isTeam
      ? (slot === 1 ? m.team1_id : m.team2_id)
      : (slot === 1 ? (m.manual_entry1_id ?? m.player1_id) : (m.manual_entry2_id ?? m.player2_id));
    if (!winnerId) return;
    const body = isTeam ? { winner_team_id: winnerId } : (m.manual_entry1_id != null || m.manual_entry2_id != null ? { winner_manual_entry_id: winnerId } : { winner_player_id: winnerId });
    try {
      const res = await authFetch(`${API}/tournaments/${tournamentId}/bracket/matches/${matchId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      let errMsg = 'Failed to set winner';
      if (!res.ok) {
        try {
          const data = await res.json();
          errMsg = data?.detail || data?.error || errMsg;
        } catch {
          /* response may be HTML from nginx */
        }
        throw new Error(errMsg);
      }
      await fetchData({ silent: true });
    } catch (err) {
      setError(err.message);
    }
  };

  const advanceOpponent = async (matchId, slot) => {
    const m = bracket?.rounds && Object.values(bracket.rounds).flat().find((x) => x.id === matchId);
    if (!m) return;
    const isTeam = bracket?.tournament?.format !== '1v1';
    const opponentSlot = slot === 1 ? 2 : 1;
    const winnerId = isTeam
      ? (opponentSlot === 1 ? m.team1_id : m.team2_id)
      : (opponentSlot === 1 ? (m.manual_entry1_id ?? m.player1_id) : (m.manual_entry2_id ?? m.player2_id));
    if (!winnerId) return;
    const body = isTeam ? { winner_team_id: winnerId } : (m.manual_entry1_id != null || m.manual_entry2_id != null ? { winner_manual_entry_id: winnerId } : { winner_player_id: winnerId });
    if (slot === 1) {
      if (isTeam) body.team1_id = null; else body[m.manual_entry1_id != null ? 'manual_entry1_id' : 'player1_id'] = null;
    } else {
      if (isTeam) body.team2_id = null; else body[m.manual_entry2_id != null ? 'manual_entry2_id' : 'player2_id'] = null;
    }
    try {
      const res = await authFetch(`${API}/tournaments/${tournamentId}/bracket/matches/${matchId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      let errMsg = 'Failed to advance';
      if (!res.ok) {
        try {
          const data = await res.json();
          errMsg = data?.detail || data?.error || errMsg;
        } catch {
          /* response may be HTML from nginx */
        }
        throw new Error(errMsg);
      }
      await fetchData({ silent: true });
    } catch (err) {
      setError(err.message);
    }
  };

  const renameTournament = async () => {
    if (!renameValue.trim()) return;
    try {
      const res = await authFetch(`${API}/tournaments/${tournamentId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: renameValue.trim() }),
      });
      const data = await parseJson(res);
      if (!res.ok) throw new Error(data?.detail || 'Failed to rename');
      setRenameValue('');
      await fetchTournaments();
    } catch (err) {
      setError(err.message);
    }
  };

  const cloneTournament = async () => {
    try {
      const res = await authFetch(`${API}/tournaments/${tournamentId}/clone`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      const data = await parseJson(res);
      if (!res.ok) throw new Error(data?.detail || 'Failed to clone');
      await fetchTournaments();
      setTournamentId(data.id);
    } catch (err) {
      setError(err.message);
    }
  };

  const updateTournamentFormat = async (newFormat) => {
    try {
      const res = await authFetch(`${API}/tournaments/${tournamentId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ format: newFormat }),
      });
      if (!res.ok) throw new Error('Failed to update format');
      await fetchTournaments();
      await fetchData({ silent: true });
    } catch (err) {
      setError(err.message);
    }
  };

  const deleteTournament = async () => {
    if (!window.confirm('Delete this tournament and all its participants, standby, and bracket data? This cannot be undone.')) return;
    const idToDelete = tournamentId;
    try {
      const res = await authFetch(`${API}/tournaments/${idToDelete}`, { method: 'DELETE' });
      const data = await parseJson(res);
      if (!res.ok) throw new Error(data?.detail || 'Failed to delete');
      setTournamentId(null);
      setBracket(null);
      const list = await fetchTournaments();
      const next = list.find((t) => t.id !== idToDelete);
      if (next) setTournamentId(next.id);
    } catch (err) {
      setError(err.message);
    }
  };

  const generateBracket = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authFetch(`${API}/tournaments/${tournamentId}/bracket/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ use_manual_order: true, bracket_type: bracketType }),
      });
      const data = await parseJson(res);
      if (!res.ok) throw new Error(data?.detail || 'Failed to generate');
      await fetchData({ silent: true });
      setActiveTab('bracket');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const resetBracket = async () => {
    if (!window.confirm('Reset bracket? This will delete the current bracket and create a fresh one from current participants/teams.')) return;
    setLoading(true);
    setError(null);
    try {
      const res = await authFetch(`${API}/tournaments/${tournamentId}/bracket/regenerate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ use_manual_order: true, bracket_type: bracketType }),
      });
      const data = await parseJson(res);
      if (!res.ok) throw new Error(data?.detail || 'Failed to regenerate');
      await fetchData({ silent: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const updateTeams = async (teamsData) => {
    try {
      const body = {
        teams: teamsData.map((t) => ({
          name: t.name,
          member_ids: t.members.map((m) => m.id),
        })),
      };
      const res = await authFetch(`${API}/tournaments/${tournamentId}/teams`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await parseJson(res);
      if (!res.ok) throw new Error(data?.detail || 'Failed to update teams');
      await fetchData({ silent: true });
    } catch (err) {
      setError(err.message);
    }
  };

  const substituteStandby = async (teamId, memberEntryId, standbyEntryId) => {
    try {
      const res = await authFetch(`${API}/tournaments/${tournamentId}/teams/substitute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ team_id: teamId, member_entry_id: memberEntryId, standby_entry_id: standbyEntryId }),
      });
      const data = await parseJson(res);
      if (!res.ok) throw new Error(data?.detail || 'Failed to substitute');
      await fetchData({ silent: true });
    } catch (err) {
      setError(err.message);
    }
  };

  const regenerateTeams = async () => {
    if (!window.confirm('Regenerate teams from participants + standby? This will replace all teams and regenerate the bracket.')) return;
    setLoading(true);
    setError(null);
    try {
      const res = await authFetch(`${API}/tournaments/${tournamentId}/teams/regenerate`, { method: 'POST' });
      const data = await parseJson(res);
      if (!res.ok) throw new Error(data?.detail || 'Failed to regenerate');
      await fetchData({ silent: true });
      setActiveTab('bracket');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  if (!authLoading && !user) {
    return null;
  }

  return (
    <div style={{ padding: 32, maxWidth: 1280, margin: '0 auto', minHeight: '100vh' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24, flexWrap: 'wrap', gap: 12 }}>
        <h1 style={{ margin: 0, fontSize: 28, fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.02em' }}>
          {siteTitle}
        </h1>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          <>
            <Link to="/winners" style={{ color: 'var(--accent)', textDecoration: 'none', fontSize: 14 }}>Winners</Link>
            {user ? (
              <>
                <span style={{ color: 'var(--text-muted)', fontSize: 14 }}>{user.username} ({user.role})</span>
                {isAdmin && (
                  <Link to="/settings" style={{ color: 'var(--accent)', textDecoration: 'none', fontSize: 14 }}>Settings</Link>
                )}
                <button onClick={logout} style={{ padding: '8px 14px', fontSize: 14 }}>Logout</button>
              </>
            ) : (
              <Link to="/login" state={{ from: location }} style={{ color: 'var(--accent)', textDecoration: 'none', fontSize: 14 }}>
                Login to edit
              </Link>
            )}
          </>
        </div>
      </div>
      <div style={{ marginBottom: 24, display: 'flex', flexWrap: 'wrap', gap: 14, alignItems: 'center', position: 'relative' }}>
        <label style={{ color: 'var(--text-secondary)' }}>Tournament:</label>
        <select
          value={tournamentId ?? ''}
          onChange={(e) => { setTournamentId(Number(e.target.value) || null); setMenuSection(null); setMenuOpen(false); }}
          style={{ padding: '10px 14px', minWidth: 220 }}
        >
          <option value="">Select...</option>
          {tournaments.map((t) => (
            <option key={t.id} value={t.id}>{t.name} ({t.format}) — {t.status === 'open' ? 'Open' : t.status === 'completed' ? 'Completed' : t.status === 'closed' ? 'Closed' : t.status} {t.archived ? '· archived' : ''}</option>
          ))}
        </select>
        {tournamentId && (() => {
          const t = tournaments.find((x) => x.id === tournamentId);
          if (!t) return null;
          const statusConfig = { open: { label: 'Open', color: 'var(--success)', bg: 'rgba(34,197,94,0.15)' }, completed: { label: 'Completed', color: '#eab308', bg: 'rgba(234,179,8,0.15)' }, closed: { label: 'Closed', color: 'var(--text-muted)', bg: 'rgba(113,113,122,0.15)' }, in_progress: { label: 'In progress', color: 'var(--accent)', bg: 'var(--accent-muted)' } };
          const cfg = statusConfig[t.status] || { label: t.status, color: 'var(--text-muted)', bg: 'rgba(113,113,122,0.15)' };
          return (
            <span style={{ fontSize: 12, fontWeight: 600, padding: '4px 10px', borderRadius: 20, color: cfg.color, background: cfg.bg, border: `1px solid ${cfg.color}40` }}>
              {cfg.label}
            </span>
          );
        })()}
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 14, color: 'var(--text-secondary)' }}>
          <input type="checkbox" checked={showArchived} onChange={(e) => { setShowArchived(e.target.checked); fetchTournaments(e.target.checked); }} />
          Show archived
        </label>
        {canEdit && (
          <div style={{ position: 'relative' }}>
            <button
              onClick={() => setMenuOpen((o) => !o)}
              style={{ padding: '10px 14px', fontSize: 18, lineHeight: 1 }}
              title="Tournament actions"
            >
              ☰
            </button>
            {menuOpen && (
              <>
                <div style={{ position: 'fixed', inset: 0, zIndex: 10 }} onClick={() => { setMenuOpen(false); setMenuSection(null); }} aria-hidden="true" />
                <div
                  style={{
                    position: (menuSection === 'deadline' || menuSection === 'create') ? 'fixed' : 'absolute',
                    ...(menuSection === 'deadline' || menuSection === 'create'
                      ? { top: '50%', left: '50%', transform: 'translate(-50%, -50%)', minWidth: 360, maxWidth: 'min(420px, 95vw)' }
                      : { top: '100%', left: 0, marginTop: 4, minWidth: 260 }),
                    background: 'var(--bg-secondary)',
                    border: '1px solid var(--border)',
                    borderRadius: 'var(--radius)',
                    boxShadow: 'var(--shadow)',
                    zIndex: 20,
                    padding: 16,
                  }}
                >
                  {menuSection === null ? (
                    <>
                      <button onClick={() => { fetchData(); setMenuOpen(false); }} style={{ display: 'block', width: '100%', textAlign: 'left', padding: '10px 12px', marginBottom: 4 }}>
                        Refresh
                      </button>
                      {tournamentId && (
                        <>
                          <button onClick={() => { setMenuSection('rename'); setRenameValue(tournaments.find((t) => t.id === tournamentId)?.name ?? ''); }} style={{ display: 'block', width: '100%', textAlign: 'left', padding: '10px 12px', marginBottom: 4 }}>
                            Rename
                          </button>
                          <button onClick={async () => { setMenuSection('deadline'); const list = await fetchTournaments(); const d = list?.find((t) => t.id === tournamentId)?.registration_deadline; setDeadlineValue(d ? utcToDatetimeLocal(d) : ''); }} style={{ display: 'block', width: '100%', textAlign: 'left', padding: '10px 12px', marginBottom: 4 }} title="Registration signup deadline">
                            Set deadline
                          </button>
                          {discordConfigReady && tournaments.find((t) => t.id === tournamentId)?.status === 'open' && (
                            <button
                              onClick={async () => {
                                try {
                                  const res = await authFetch(`${API}/tournaments/${tournamentId}/post-signup`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) });
                                  const data = await res.json();
                                  if (!res.ok) throw new Error(data?.detail || 'Failed to post');
                                  setError('');
                                  setMenuOpen(false);
                                } catch (err) {
                                  setError(err.message);
                                }
                              }}
                              style={{ display: 'block', width: '100%', textAlign: 'left', padding: '10px 12px', marginBottom: 4 }}
                              title="Post signup message to Discord"
                            >
                              Post signup to Discord
                            </button>
                          )}
                          <button onClick={() => { cloneTournament(); setMenuOpen(false); }} style={{ display: 'block', width: '100%', textAlign: 'left', padding: '10px 12px', marginBottom: 4 }} title="Copy participants and standby to a new tournament">
                            Clone
                          </button>
                          {['completed', 'closed'].includes(tournaments.find((t) => t.id === tournamentId)?.status) && (
                            <button
                              onClick={async () => {
                                try {
                                  await authFetch(`${API}/tournaments/${tournamentId}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'open' }) });
                                  await fetchTournaments(showArchived);
                                  setMenuOpen(false);
                                } catch (err) {
                                  setError(err.message);
                                }
                              }}
                              style={{ display: 'block', width: '100%', textAlign: 'left', padding: '10px 12px', marginBottom: 4 }}
                              title="Re-open registration"
                            >
                              Re-open tournament
                            </button>
                          )}
                          <button onClick={async () => { try { await authFetch(`${API}/tournaments/${tournamentId}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ archived: !tournaments.find((t) => t.id === tournamentId)?.archived }) }); await fetchTournaments(showArchived); setMenuOpen(false); } catch (err) { setError(err.message); } }} style={{ display: 'block', width: '100%', textAlign: 'left', padding: '10px 12px', marginBottom: 4 }} title="Archive to hide from default list">
                            {tournaments.find((t) => t.id === tournamentId)?.archived ? 'Unarchive' : 'Archive'}
                          </button>
                          <div style={{ borderTop: '1px solid var(--border)', margin: '8px 0' }} />
                          <button onClick={() => deleteTournament()} style={{ display: 'block', width: '100%', textAlign: 'left', padding: '10px 12px', color: 'var(--error)' }}>
                            Delete
                          </button>
                          <div style={{ borderTop: '1px solid var(--border)', margin: '8px 0' }} />
                          <div style={{ padding: '8px 0 4px', fontSize: 11, color: 'var(--text-muted)' }}>Format:</div>
                          <select
                            value={tournaments.find((t) => t.id === tournamentId)?.format ?? '1v1'}
                            onChange={(e) => { updateTournamentFormat(e.target.value); setMenuOpen(false); }}
                            style={{ width: '100%', marginBottom: 8 }}
                          >
                            <option value="1v1">1v1</option>
                            <option value="2v2">2v2</option>
                            <option value="3v3">3v3</option>
                            <option value="4v4">4v4</option>
                          </select>
                        </>
                      )}
                      <div style={{ borderTop: '1px solid var(--border)', margin: '8px 0' }} />
                      <button onClick={() => { setMenuSection('create'); setNewTournamentName(''); setNewTournamentDeadline(''); }} style={{ display: 'block', width: '100%', textAlign: 'left', padding: '10px 12px' }}>
                        Create new tournament
                      </button>
                    </>
                  ) : menuSection === 'rename' ? (
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8 }}>Rename tournament</div>
                      <input
                        type="text"
                        placeholder="New name"
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && renameTournament()}
                        style={{ width: '100%', marginBottom: 8 }}
                        autoFocus
                      />
                      <div style={{ display: 'flex', gap: 8 }}>
                        <button className="primary" onClick={() => { renameTournament(); setMenuSection(null); setMenuOpen(false); }} disabled={!renameValue.trim()}>Save</button>
                        <button onClick={() => { setMenuSection(null); setRenameValue(''); }}>Cancel</button>
                      </div>
                    </div>
                  ) : menuSection === 'deadline' ? (
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8 }}>Signup deadline</div>
                      <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Paste from Discord (e.g. &lt;t:1771834500:R&gt;)</label>
                      <input
                        type="text"
                        placeholder="<t:1771834500:R>"
                        onPaste={(e) => { const v = parseDiscordTimestamp(e.clipboardData.getData('text')); if (v) { e.preventDefault(); setDeadlineValue(v); } }}
                        onChange={(e) => { const v = parseDiscordTimestamp(e.target.value); if (v) setDeadlineValue(v); }}
                        style={{ width: '100%', marginBottom: 12, padding: '8px 10px', fontSize: 13 }}
                      />
                      <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Or pick date and time</label>
                      <div style={{ display: 'flex', gap: 12, marginBottom: 12 }}>
                        <input
                          type="date"
                          value={deadlineValue ? deadlineValue.slice(0, 10) : ''}
                          onChange={(e) => setDeadlineValue(e.target.value ? e.target.value + 'T' + (deadlineValue ? deadlineValue.slice(11, 16) : '18:00') : '')}
                          style={{ flex: 1, minWidth: 140, padding: '8px 10px' }}
                          autoFocus
                        />
                        <input
                          type="time"
                          value={deadlineValue ? deadlineValue.slice(11, 16) : '18:00'}
                          onChange={(e) => setDeadlineValue((deadlineValue ? deadlineValue.slice(0, 10) : new Date().toISOString().slice(0, 10)) + 'T' + e.target.value)}
                          style={{ flex: 1, minWidth: 100, padding: '8px 10px' }}
                        />
                      </div>
                      {deadlineValue && (
                        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 12 }}>
                          Copy for Discord: <button type="button" onClick={() => navigator.clipboard?.writeText(toDiscordTimestamp(deadlineValue, 'R')).then(() => { setError(null); setCopyFeedback('Copied!'); setTimeout(() => setCopyFeedback(null), 1500); }).catch(() => setError('Copy failed'))} style={{ padding: '4px 8px', marginRight: 6 }}>relative (:R)</button>
                          <button type="button" onClick={() => navigator.clipboard?.writeText(toDiscordTimestamp(deadlineValue, 'F')).then(() => { setError(null); setCopyFeedback('Copied!'); setTimeout(() => setCopyFeedback(null), 1500); }).catch(() => setError('Copy failed'))} style={{ padding: '4px 8px', marginRight: 6 }}>full (:F)</button>
                          {copyFeedback && <span style={{ color: 'var(--success)', marginLeft: 4 }}>{copyFeedback}</span>}
                        </div>
                      )}
                      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                        <button className="primary" onClick={async () => {
                          try {
                            const body = { registration_deadline: deadlineValue ? new Date(deadlineValue).toISOString() : '' };
                            const res = await authFetch(`${API}/tournaments/${tournamentId}`, {
                              method: 'PATCH',
                              headers: { 'Content-Type': 'application/json' },
                              body: JSON.stringify(body),
                            });
                            if (!res.ok) throw new Error((await parseJson(res))?.detail || 'Failed');
                            await fetchTournaments();
                            setMenuSection(null);
                            setMenuOpen(false);
                          } catch (err) { setError(err.message); }
                        }}>Save</button>
                        <button onClick={async () => {
                          try {
                            const res = await authFetch(`${API}/tournaments/${tournamentId}`, {
                              method: 'PATCH',
                              headers: { 'Content-Type': 'application/json' },
                              body: JSON.stringify({ registration_deadline: '' }),
                            });
                            if (!res.ok) throw new Error((await parseJson(res))?.detail || 'Failed');
                            await fetchTournaments();
                            setMenuSection(null);
                            setMenuOpen(false);
                          } catch (err) { setError(err.message); }
                        }}>Clear</button>
                        <button onClick={() => { setMenuSection(null); }}>Cancel</button>
                      </div>
                    </div>
                  ) : (
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8 }}>Create new tournament</div>
                      <input
                        type="text"
                        placeholder="Tournament name"
                        value={newTournamentName}
                        onChange={(e) => setNewTournamentName(e.target.value)}
                        style={{ width: '100%', marginBottom: 8 }}
                        autoFocus
                      />
                      <select value={newTournamentFormat} onChange={(e) => setNewTournamentFormat(e.target.value)} style={{ width: '100%', marginBottom: 8 }}>
                        <option value="1v1">1v1</option>
                        <option value="2v2">2v2</option>
                        <option value="3v3">3v3</option>
                        <option value="4v4">4v4</option>
                      </select>
                      <label style={{ fontSize: 12, color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>Signup deadline (optional)</label>
                      <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Paste from Discord (e.g. &lt;t:1771834500:R&gt;)</label>
                      <input
                        type="text"
                        placeholder="<t:1771834500:R>"
                        onPaste={(e) => { const v = parseDiscordTimestamp(e.clipboardData.getData('text')); if (v) { e.preventDefault(); setNewTournamentDeadline(v); } }}
                        onChange={(e) => { const v = parseDiscordTimestamp(e.target.value); if (v) setNewTournamentDeadline(v); }}
                        style={{ width: '100%', marginBottom: 8, padding: '8px 10px', fontSize: 13 }}
                      />
                      <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Or pick date and time</label>
                      <div style={{ display: 'flex', gap: 12, marginBottom: 8 }}>
                        <input
                          type="date"
                          value={newTournamentDeadline ? newTournamentDeadline.slice(0, 10) : ''}
                          onChange={(e) => setNewTournamentDeadline(e.target.value ? e.target.value + 'T' + (newTournamentDeadline ? newTournamentDeadline.slice(11, 16) : '18:00') : '')}
                          style={{ flex: 1, minWidth: 140, padding: '8px 10px' }}
                        />
                        <input
                          type="time"
                          value={newTournamentDeadline ? newTournamentDeadline.slice(11, 16) : '18:00'}
                          onChange={(e) => setNewTournamentDeadline((newTournamentDeadline ? newTournamentDeadline.slice(0, 10) : new Date().toISOString().slice(0, 10)) + 'T' + e.target.value)}
                          style={{ flex: 1, minWidth: 100, padding: '8px 10px' }}
                        />
                      </div>
                      {newTournamentDeadline && (
                        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8 }}>
                          Copy for Discord: <button type="button" onClick={() => navigator.clipboard?.writeText(toDiscordTimestamp(newTournamentDeadline, 'R')).then(() => { setError(null); setCopyFeedback('Copied!'); setTimeout(() => setCopyFeedback(null), 1500); }).catch(() => setError('Copy failed'))} style={{ padding: '4px 8px', marginRight: 6 }}>relative (:R)</button>
                          <button type="button" onClick={() => navigator.clipboard?.writeText(toDiscordTimestamp(newTournamentDeadline, 'F')).then(() => { setError(null); setCopyFeedback('Copied!'); setTimeout(() => setCopyFeedback(null), 1500); }).catch(() => setError('Copy failed'))} style={{ padding: '4px 8px', marginRight: 6 }}>full (:F)</button>
                          {copyFeedback && <span style={{ color: 'var(--success)', marginLeft: 4 }}>{copyFeedback}</span>}
                        </div>
                      )}
                      <div style={{ display: 'flex', gap: 8 }}>
                        <button
                          className="primary"
                          onClick={async () => {
                            if (!newTournamentName.trim()) return;
                            try {
                              const body = { name: newTournamentName.trim(), format: newTournamentFormat };
                              if (newTournamentDeadline) {
                                body.registration_deadline = new Date(newTournamentDeadline).toISOString();
                              }
                              const res = await authFetch(`${API}/tournaments`, {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(body),
                              });
                              const data = await parseJson(res);
                              if (!res.ok) throw new Error(data?.detail || 'Failed');
                              setNewTournamentName('');
                              setNewTournamentDeadline('');
                              setMenuSection(null);
                              setMenuOpen(false);
                              await fetchTournaments();
                              setTournamentId(data.id);
                            } catch (err) {
                              setError(err.message);
                            }
                          }}
                          disabled={!newTournamentName.trim()}
                        >
                          Create
                        </button>
                        <button onClick={() => { setMenuSection(null); setNewTournamentName(''); setNewTournamentDeadline(''); }}>Cancel</button>
                      </div>
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        )}
      </div>
      {error && (
        <div style={{ padding: 14, marginBottom: 20, background: 'rgba(239,68,68,0.15)', border: '1px solid var(--error)', borderRadius: 'var(--radius-sm)', color: 'var(--error)' }}>
          {error}
        </div>
      )}
      {loading && (
        <p style={{ color: 'var(--text-muted)' }}>Loading...</p>
      )}
      {tournamentId && !loading && (
        <>
          {(() => {
            const fmt = tournaments.find((t) => t.id === tournamentId)?.format;
            const isTeamFormat = fmt && fmt !== '1v1';
            const tabs = ['players', ...(isTeamFormat ? ['teams'] : []), 'bracket'];
            return (
              <div style={{ display: 'flex', gap: 10, marginBottom: 28 }}>
                {tabs.map((tab) => {
                  const path = tab === 'players' ? '/' : `/${tab}`;
                  return (
                    <Link
                      key={tab}
                      to={path}
                      style={{
                        ...styles.tab(activeTab === tab),
                        textDecoration: 'none',
                      }}
                    >
                      {tab === 'players' ? 'Players' : tab.charAt(0).toUpperCase() + tab.slice(1)}
                    </Link>
                  );
                })}
              </div>
            );
          })()}
          {activeTab === 'players' && (
            <ParticipantsAndStandbyView
              participants={participants}
              standby={standby}
              onAddParticipant={addParticipant}
              onAddStandby={addStandby}
              onRemoveParticipant={removeParticipant}
              onRemoveStandby={removeStandby}
              onReorderParticipants={reorderParticipants}
              onReorderStandby={reorderStandby}
              onRenameParticipant={renameParticipant}
              onRenameStandby={renameStandby}
              onMoveEntry={moveEntry}
              readOnly={!canEdit}
            />
          )}
          {activeTab === 'teams' && (
            <TeamsView
              teams={teams}
              participants={participants}
              standby={standby}
              onUpdateTeams={updateTeams}
              onSubstitute={substituteStandby}
              onRegenerate={regenerateTeams}
              format={tournaments.find((t) => t.id === tournamentId)?.format}
              readOnly={!canEdit}
            />
          )}
          {activeTab === 'bracket' && (() => {
            const fmt = tournaments.find((t) => t.id === tournamentId)?.format;
            const bracketCount = fmt === '1v1' ? participants.length : (teams?.length ?? 0);
            const generateDisabled = !bracketCount || (bracketType === 'double_elim' && bracketCount < 8);
            return (
            <div>
              {bracket?.error ? (
                <div>
                  <div style={styles.card}>
                    <p style={{ color: 'var(--text-secondary)', marginBottom: 16 }}>{bracket.error}</p>
                    <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap', marginBottom: 16 }}>
                      <label style={{ color: 'var(--text-secondary)' }}>Bracket type:</label>
                      <select value={bracketType} onChange={(e) => setBracketType(e.target.value)} style={{ padding: '8px 12px' }} title={bracketType === 'double_elim' ? 'Double elimination requires 8+ teams' : undefined}>
                        <option value="single_elim">Single elimination</option>
                        <option value="double_elim">Double elimination (8+ teams)</option>
                      </select>
                    </div>
                    {canEdit && <button className="primary" onClick={generateBracket} disabled={generateDisabled} title={generateDisabled && bracketType === 'double_elim' ? 'Double elimination requires 8+ teams' : undefined}>
                      Generate Bracket
                    </button>}
                  </div>
                  {previewBracket && Object.keys(previewBracket.rounds || {}).length > 0 && (
                    <div style={{ marginTop: 24 }}>
                      <h3 style={{ margin: '0 0 12px', color: 'var(--text-secondary)' }}>Preview</h3>
                      <BracketView bracket={previewBracket} tournament={previewBracket.tournament} teams={teams} participants={participants} standby={standby} isPreview canEdit={false} />
                    </div>
                  )}
                </div>
              ) : bracket && Object.keys(bracket.rounds || {}).length > 0 ? (
                <div>
                  {canEdit && (
                    <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap', marginBottom: 16 }}>
                      <button onClick={resetBracket} disabled={loading || generateDisabled} title={generateDisabled && bracketType === 'double_elim' ? 'Double elimination requires 8+ teams' : 'Delete bracket and create a fresh one from current participants/teams'}>
                        Reset
                      </button>
                    </div>
                  )}
                  <BracketView bracket={bracket} tournament={bracket.tournament} teams={teams} participants={participants} standby={standby} onUpdateMatch={updateMatch} onAdvanceOpponent={advanceOpponent} onSetWinner={setWinner} onSwapWinner={swapWinner} onClearWinner={clearWinner} onSwapSlots={swapSlots} canEdit={canEdit} />
                </div>
              ) : previewBracket && Object.keys(previewBracket.rounds || {}).length > 0 ? (
                <div>
                  <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap', marginBottom: 16 }}>
                    <span style={{ color: 'var(--text-muted)', fontSize: 14 }}>Preview</span>
                    <label style={{ color: 'var(--text-secondary)' }}>Bracket type:</label>
                    <select value={bracketType} onChange={(e) => setBracketType(e.target.value)} style={{ padding: '8px 12px' }}>
                      <option value="single_elim">Single elimination</option>
                      <option value="double_elim">Double elimination</option>
                    </select>
                    {canEdit && <button className="primary" onClick={generateBracket} disabled={generateDisabled} title={generateDisabled && bracketType === 'double_elim' ? 'Double elimination requires 8+ teams' : undefined}>Generate Bracket</button>}
                  </div>
                  <BracketView bracket={previewBracket} tournament={previewBracket.tournament} teams={teams} participants={participants} standby={standby} isPreview canEdit={false} />
                </div>
              ) : (
                <div style={styles.card}>
                  <p style={{ color: 'var(--text-secondary)', marginBottom: 16 }}>No bracket yet. Add participants{ tournaments.find((t) => t.id === tournamentId)?.format !== '1v1' ? ' and teams' : '' }, then generate.</p>
                  <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap', marginBottom: 16 }}>
                    <label style={{ color: 'var(--text-secondary)' }}>Bracket type:</label>
                    <select value={bracketType} onChange={(e) => setBracketType(e.target.value)} style={{ padding: '8px 12px' }} title={bracketType === 'double_elim' ? 'Double elimination requires 8+ teams' : undefined}>
                      <option value="single_elim">Single elimination</option>
                      <option value="double_elim">Double elimination (8+ teams)</option>
                    </select>
                  </div>
                  {canEdit && <button className="primary" onClick={generateBracket} disabled={generateDisabled} title={generateDisabled && bracketType === 'double_elim' ? 'Double elimination requires 8+ teams' : undefined}>
                    Generate Bracket
                  </button>}
                </div>
              )}
            </div>
          );
          })()}
        </>
      )}
    </div>
  );
}

export default App;
