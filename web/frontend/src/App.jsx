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
      const entryId = Number(activeId.replace('p-', ''));
      onMoveEntry?.(entryId, 'standby');
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
                {participants.map((item) => (
                  <RosterItem
                    key={item.id}
                    item={item}
                    prefix="p"
                    label={item.display_name}
                    onRename={onRenameParticipant}
                    onRemove={onRemoveParticipant}
                    onMoveUp={(id) => moveUp(participants, id, onReorderParticipants)}
                    onMoveDown={(id) => moveDown(participants, id, onReorderParticipants)}
                    canRemove={true}
                    canRename={true}
                    readOnly={readOnly}
                  />
                ))}
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

function TeamSlot({ name, teamId, teams, isTeam, title }) {
  const [showTooltip, setShowTooltip] = useState(false);
  const team = isTeam && teams?.length
    ? (teamId ? teams.find((t) => t.id === teamId) : teams.find((t) => t.name === name))
    : null;
  const members = team?.members || [];
  const hasMembers = members.length > 0;

  return (
    <div
      style={{ position: 'relative', display: 'inline-block' }}
      onMouseEnter={() => hasMembers && setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
    >
      <span style={{ cursor: hasMembers ? 'help' : 'default' }} title={title || (hasMembers ? 'Hover for team list' : null)}>
        {name || 'TBD'}
      </span>
      {showTooltip && hasMembers && (
        <div
          style={{
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
          }}
        >
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--accent)', marginBottom: 6 }}>{team.name}</div>
          {members.map((m) => (
            <div key={m.id} style={{ fontSize: 13, color: 'var(--text-primary)' }}>• {m.display_name}</div>
          ))}
        </div>
      )}
    </div>
  );
}

function MatchSlot({ label, name, matchId, slot, onDrop, onAdvanceOpponent, hasOpponent }) {
  const [isOver, setIsOver] = useState(false);
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
        }}
        onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; setIsOver(true); }}
        onDragLeave={() => setIsOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setIsOver(false);
          const data = e.dataTransfer.getData('application/json');
          if (data && onDrop) onDrop(matchId, slot, JSON.parse(data));
        }}
      >
        {name || label}
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
    const entryId = Number(activeId.replace('player-', ''));
    if (overId === 'unassigned') {
      const newTeams = teams.map((t) => ({
        id: t.id,
        name: t.name,
        members: t.members.filter((m) => m.id !== entryId),
      })).filter((t) => t.members.length > 0 || t.id);
      onUpdateTeams(newTeams);
    } else if (overId.startsWith('player-')) {
      const targetId = Number(overId.replace('player-', ''));
      if (targetId === entryId) return;
      const person = allPeople.find((p) => p.id === entryId);
      const targetPerson = allPeople.find((p) => p.id === targetId);
      if (!person || !targetPerson) return;
      const currentTeam = teams.find((t) => t.members.some((m) => m.id === entryId));
      const targetTeam = teams.find((t) => t.members.some((m) => m.id === targetId));
      const newTeams = teams.map((t) => {
        const isCurrent = currentTeam && String(t.id) === String(currentTeam.id);
        const isTarget = targetTeam && String(t.id) === String(targetTeam.id);
        if (isCurrent && isTarget) {
          return { ...t, members: t.members.map((m) => m.id === entryId ? { id: targetPerson.id, display_name: targetPerson.display_name } : m.id === targetId ? { id: person.id, display_name: person.display_name } : m) };
        }
        if (isCurrent) {
          return { ...t, members: t.members.map((m) => m.id === entryId ? { id: targetPerson.id, display_name: targetPerson.display_name } : m) };
        }
        if (isTarget) {
          return { ...t, members: t.members.map((m) => m.id === targetId ? { id: person.id, display_name: person.display_name } : m) };
        }
        return t;
      });
      onUpdateTeams(newTeams);
    } else if (overId.startsWith('team-')) {
      const teamId = overId.replace('team-', '');
      const targetTeam = teams.find((t) => String(t.id) === teamId);
      if (!targetTeam || targetTeam.members.length >= maxPerTeam) return;
      const currentTeam = teams.find((t) => t.members.some((m) => m.id === entryId));
      const person = allPeople.find((p) => p.id === entryId);
      if (!person) return;
      let newTeams;
      if (currentTeam) {
        newTeams = teams.map((t) => {
          if (String(t.id) === teamId) {
            if (t.members.some((m) => m.id === entryId)) return t;
            return { ...t, members: [...t.members, { id: person.id, display_name: person.display_name }] };
          }
          if (String(t.id) === String(currentTeam.id)) {
            return { ...t, members: t.members.filter((m) => m.id !== entryId) };
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

function BracketBox({ name, isWinner, accentSide, teams, teamId, isTeam, isPreview, onDrop, matchId, slot, onAdvanceOpponent, onSetWinner, hasOpponent, canSetWinner, canEdit }) {
  const content = isTeam && teams?.length ? (
    <TeamSlot name={name} teamId={teamId} teams={teams} isTeam={true} />
  ) : (
    <span>{name || 'TBD'}</span>
  );
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
  return (
    <div
      style={{ ...boxStyle, cursor: (canClickWinner || showWinnerBtn) ? 'pointer' : 'default' }}
      onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; }}
      onDrop={(e) => {
        e.preventDefault();
        const data = e.dataTransfer.getData('application/json');
        if (data && onDrop) onDrop(matchId, slot, JSON.parse(data));
      }}
      onClick={canClickWinner ? () => onSetWinner(matchId, slot) : undefined}
      title={canClickWinner ? 'Click to set as winner' : (isDropout ? 'Opponent dropped — click to advance winner' : (typeof name === 'string' ? name : undefined))}
    >
      <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0, flex: 1 }}>{content}</div>
      {showWinnerBtn && (
        <button onClick={(ev) => { ev.stopPropagation(); handleWinnerClick(); }} style={{ marginLeft: 8, fontSize: 10, padding: '2px 6px', flexShrink: 0 }} title={canClickWinner ? 'Set as winner' : 'Advance winner'}>✓</button>
      )}
    </div>
  );
}

function BracketVisual({ rounds, isTeam, teams, isPreview, onUpdateMatch, onAdvanceOpponent, onSetWinner }) {
  const roundEntries = Object.entries(rounds || {}).filter(([k]) => Number(k) < 10).sort((a, b) => Number(a[0]) - Number(b[0]));
  if (roundEntries.length === 0) return <p style={{ color: 'var(--text-muted)', padding: 24 }}>No matches to display.</p>;

  const slotH = 44;
  const matchGap = 24;
  const colW = 180;
  const colGap = 32;

  const renderMatchBlock = (m) => {
    const s1 = m.team1_name || m.player1_name || 'TBD';
    const s2 = m.team2_name || m.player2_name || 'TBD';
    const w1 = m.winner_name === s1;
    const w2 = m.winner_name === s2;
    const bothFilled = (m.team1_id || m.manual_entry1_id || m.player1_id) && (m.team2_id || m.manual_entry2_id || m.player2_id);
    const canSetWinner = bothFilled && !m.winner_name;
    return (
      <div key={m.id} style={{ display: 'flex', flexDirection: 'column', gap: 0, minWidth: colW }}>
        <BracketBox name={s1} isWinner={w1} accentSide="left" teams={teams} teamId={m.team1_id} isTeam={isTeam} isPreview={isPreview} onDrop={onUpdateMatch} matchId={m.id} slot={1} onAdvanceOpponent={onAdvanceOpponent} onSetWinner={onSetWinner} hasOpponent={!!(m.team2_id || m.manual_entry2_id || m.player2_id)} canSetWinner={canSetWinner} canEdit={!!onUpdateMatch} />
        <div style={{ height: 1, background: 'var(--border)', margin: '2px 0' }} />
        <BracketBox name={s2} isWinner={w2} accentSide="left" teams={teams} teamId={m.team2_id} isTeam={isTeam} isPreview={isPreview} onDrop={onUpdateMatch} matchId={m.id} slot={2} onAdvanceOpponent={onAdvanceOpponent} onSetWinner={onSetWinner} hasOpponent={!!(m.team1_id || m.manual_entry1_id || m.player1_id)} canSetWinner={canSetWinner} canEdit={!!onUpdateMatch} />
        {m.winner_name && (
          <div style={{ marginTop: 6, fontSize: 11, color: 'var(--success)', fontWeight: 600 }}>
            → {m.winner_name}
          </div>
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
            {matches.map((m) => m && renderMatchBlock(m))}
          </div>
        ))}
      </div>
    </div>
  );
}

function BracketTree({ rounds, isTeam, teams, isPreview, onUpdateMatch, onAdvanceOpponent }) {
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
              <MatchSlot label="Slot 1" name={s1} matchId={m.id} slot={1} onDrop={onUpdateMatch} onAdvanceOpponent={onAdvanceOpponent} hasOpponent={!!(m.team2_id || m.manual_entry2_id || m.player2_id)} teamId={m.team1_id} teams={teams} isTeam={isTeam} />
              <span style={{ display: 'block', textAlign: 'center', color: 'var(--text-muted)', fontSize: 11, margin: '4px 0' }}>vs</span>
              <MatchSlot label="Slot 2" name={s2} matchId={m.id} slot={2} onDrop={onUpdateMatch} onAdvanceOpponent={onAdvanceOpponent} hasOpponent={!!(m.team1_id || m.manual_entry1_id || m.player1_id)} teamId={m.team2_id} teams={teams} isTeam={isTeam} />
            </>
          ) : (
            <>
              {renderSlot(m, 1, s1, m.team1_id)}
              <span style={{ display: 'block', textAlign: 'center', color: 'var(--text-muted)', fontSize: 11, margin: '4px 0' }}>vs</span>
              {renderSlot(m, 2, s2, m.team2_id)}
            </>
          )}
          {m.winner_name && (
            <div style={{ marginTop: 6, fontSize: 11, color: 'var(--success)', fontWeight: 600 }}>
              → {m.winner_name}
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

function BracketView({ bracket, tournament, teams, participants, standby, onUpdateMatch, onAdvanceOpponent, onSetWinner, isPreview, canEdit }) {
  const isTeam = tournament?.format !== '1v1';
  const teamsToUse = (bracket?.teams && bracket.teams.length > 0) ? bracket.teams : (teams || []);
  const pool = isTeam
    ? (teams || []).map((t) => ({ id: t.id, name: t.name, type: 'team' }))
    : [...(participants || []), ...(standby || [])].map((p) => ({ ...p, type: 'manual_entry' }));

  const allMatches = bracket?.rounds ? Object.values(bracket.rounds).flat() : [];
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
                <MatchSlot label="Slot 1" name={s1} matchId={m.id} slot={1} onDrop={canEdit ? onUpdateMatch : null} onAdvanceOpponent={canEdit ? onAdvanceOpponent : null} hasOpponent={!!(m.team2_id || m.manual_entry2_id || m.player2_id)} teamId={m.team1_id} teams={teamsToUse} isTeam={isTeam} />
                <span style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>vs</span>
                <MatchSlot label="Slot 2" name={s2} matchId={m.id} slot={2} onDrop={canEdit ? onUpdateMatch : null} onAdvanceOpponent={canEdit ? onAdvanceOpponent : null} hasOpponent={!!(m.team1_id || m.manual_entry1_id || m.player1_id)} teamId={m.team2_id} teams={teamsToUse} isTeam={isTeam} />
                  </>
                )}
                {m.winner_name && (
                  <div style={{ marginTop: 8, color: 'var(--success)', fontWeight: 600, fontSize: 14 }}>
                    Winner: {m.winner_name}
                  </div>
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
    const rounds = bracket?.rounds ? Object.entries(bracket.rounds).filter(([k]) => Number(k) < 10).sort((a, b) => Number(a[0]) - Number(b[0])) : [];
    const roundsObj = Object.fromEntries(rounds);
    return (
        <BracketVisual
        rounds={roundsObj}
        isTeam={isTeam}
        teams={teamsToUse}
        isPreview={isPreview}
        onUpdateMatch={canEdit ? onUpdateMatch : null}
        onAdvanceOpponent={canEdit ? onAdvanceOpponent : null}
        onSetWinner={canEdit ? onSetWinner : null}
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
            <BracketTree rounds={Object.fromEntries(Object.entries(wByRound).sort((a, b) => a[0] - b[0]))} isTeam={isTeam} teams={teamsToUse} isPreview={isPreview} onUpdateMatch={onUpdateMatch} onAdvanceOpponent={onAdvanceOpponent} />
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
    <div style={{ marginTop: 24, display: 'flex', gap: 32 }}>
      {!isPreview && canEdit && pool.length > 0 && (
        <div style={{ minWidth: 200 }}>
          <h4 style={{ margin: '0 0 12px', color: 'var(--text-secondary)', fontSize: 14, fontWeight: 600 }}>Drag to assign</h4>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {pool.map((p) => (
              <DraggableEntity key={p.id} entity={p} />
            ))}
          </div>
        </div>
      )}
      <div style={{ flex: 1, minWidth: 0 }}>
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

  useEffect(() => {
    if (!authLoading && !user) {
      navigate('/login', { replace: true, state: { from: location } });
    }
  }, [authLoading, user, navigate, location]);

  if (!authLoading && !user) {
    return null;
  }
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
  const [bracketType, setBracketType] = useState('single_elim');
  const [editingName, setEditingName] = useState(false);
  const [renameValue, setRenameValue] = useState('');

  const fetchTournaments = async () => {
    try {
      const res = await authFetch(`${API}/tournaments`);
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
    fetch(`${API}/settings`).then((r) => r.json()).then((s) => {
      setSiteTitle(s.site_title || 'Octane Bracket Manager');
      if (s.accent_color) document.documentElement.style.setProperty('--accent', s.accent_color);
      if (s.accent_hover) document.documentElement.style.setProperty('--accent-hover', s.accent_hover);
      if (s.bg_primary) document.documentElement.style.setProperty('--bg-primary', s.bg_primary);
      if (s.bg_secondary) document.documentElement.style.setProperty('--bg-secondary', s.bg_secondary);
    }).catch(() => {});
  }, []);

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
      await authFetch(`${API}/tournaments/${tournamentId}/participants/${id}`, { method: 'DELETE' });
      await fetchData({ silent: true });
    } catch (err) {
      setError(err.message);
    }
  };

  const reorderParticipants = async (entryIds) => {
    try {
      await authFetch(`${API}/tournaments/${tournamentId}/participants/reorder`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ entry_ids: entryIds }),
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
      setEditingName(false);
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

  const regenerateBracket = async () => {
    if (!window.confirm('Regenerate bracket? This will replace the current bracket with a fresh one from current participants/teams.')) return;
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

  return (
    <div style={{ padding: 32, maxWidth: 1280, margin: '0 auto', minHeight: '100vh' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24, flexWrap: 'wrap', gap: 12 }}>
        <h1 style={{ margin: 0, fontSize: 28, fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.02em' }}>
          {siteTitle}
        </h1>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
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
        </div>
      </div>
      <div style={{ marginBottom: 24, display: 'flex', flexWrap: 'wrap', gap: 14, alignItems: 'center' }}>
        <label style={{ color: 'var(--text-secondary)' }}>Tournament:</label>
        <select
          value={tournamentId ?? ''}
          onChange={(e) => { setTournamentId(Number(e.target.value) || null); setEditingName(false); }}
          style={{ padding: '10px 14px', minWidth: 220 }}
        >
          <option value="">Select...</option>
          {tournaments.map((t) => (
            <option key={t.id} value={t.id}>{t.name} ({t.format})</option>
          ))}
        </select>
        <button onClick={fetchData}>Refresh</button>
        {tournamentId && canEdit && (
          <>
            {editingName ? (
              <>
                <input
                  type="text"
                  placeholder="New name"
                  value={renameValue}
                  onChange={(e) => setRenameValue(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && renameTournament()}
                  style={{ padding: '10px 14px', width: 180 }}
                  autoFocus
                />
                <button className="primary" onClick={renameTournament} disabled={!renameValue.trim()}>Save</button>
                <button onClick={() => { setEditingName(false); setRenameValue(''); }}>Cancel</button>
              </>
            ) : (
              <button onClick={() => { setEditingName(true); setRenameValue(tournaments.find((t) => t.id === tournamentId)?.name ?? ''); }}>Rename</button>
            )}
            <button onClick={cloneTournament} title="Copy participants and standby to a new tournament">Clone</button>
            <button onClick={deleteTournament} style={{ color: 'var(--error)' }}>Delete</button>
            <label style={{ marginLeft: 8, color: 'var(--text-muted)' }}>Format:</label>
            <select
              value={tournaments.find((t) => t.id === tournamentId)?.format ?? '1v1'}
              onChange={(e) => updateTournamentFormat(e.target.value)}
              style={{ padding: '8px 12px' }}
              title="Change tournament format (clears teams/bracket when switching)"
            >
              <option value="1v1">1v1</option>
              <option value="2v2">2v2</option>
              <option value="3v3">3v3</option>
              <option value="4v4">4v4</option>
            </select>
          </>
        )}
        {canEdit && <span style={{ marginLeft: 8, color: 'var(--text-muted)' }}>or create:</span>}
        {canEdit && (
          <>
        <input
          type="text"
          placeholder="Tournament name"
          value={newTournamentName}
          onChange={(e) => setNewTournamentName(e.target.value)}
          style={{ padding: '10px 14px', width: 180 }}
        />
        <select value={newTournamentFormat} onChange={(e) => setNewTournamentFormat(e.target.value)} style={{ padding: '10px 14px' }}>
          <option value="1v1">1v1</option>
          <option value="2v2">2v2</option>
          <option value="3v3">3v3</option>
          <option value="4v4">4v4</option>
        </select>
        <button
          className="primary"
          onClick={async () => {
            if (!newTournamentName.trim()) return;
            try {
              const res = await authFetch(`${API}/tournaments`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: newTournamentName.trim(), format: newTournamentFormat }),
              });
              const data = await parseJson(res);
              if (!res.ok) throw new Error(data?.detail || 'Failed');
              setNewTournamentName('');
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
          </>
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
                      <button onClick={regenerateBracket} disabled={loading || generateDisabled} title={generateDisabled && bracketType === 'double_elim' ? 'Double elimination requires 8+ teams' : 'Replace bracket with a fresh one from current participants/teams'}>
                        Regenerate Bracket
                      </button>
                    </div>
                  )}
                  <BracketView bracket={bracket} tournament={bracket.tournament} teams={teams} participants={participants} standby={standby} onUpdateMatch={updateMatch} onAdvanceOpponent={advanceOpponent} onSetWinner={setWinner} canEdit={canEdit} />
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
                    {canEdit && <button className="primary" onClick={generateBracket}>Generate Bracket</button>}
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
