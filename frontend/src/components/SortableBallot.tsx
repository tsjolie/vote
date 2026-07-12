import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  TouchSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { OptionOut } from "../api";

interface Props {
  options: OptionOut[]; // current order (top = 1st choice)
  onChange: (ordered: OptionOut[]) => void;
}

function Row({ option, rank }: { option: OptionOut; rank: number }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: option.id });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.6 : 1,
  };
  return (
    <li
      ref={setNodeRef}
      style={style}
      className="ballot-row"
      data-testid={`ballot-row-${option.id}`}
      {...attributes}
      {...listeners}
    >
      <span className="rank">{rank}</span>
      <span className="label">{option.label}</span>
      <span className="grip" aria-hidden>
        ⠿
      </span>
    </li>
  );
}

export default function SortableBallot({ options, onChange }: Props) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    // Touch support is a launch requirement (§1).
    useSensor(TouchSensor, { activationConstraint: { delay: 120, tolerance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const onDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = options.findIndex((o) => o.id === active.id);
    const newIndex = options.findIndex((o) => o.id === over.id);
    onChange(arrayMove(options, oldIndex, newIndex));
  };

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
      <SortableContext items={options.map((o) => o.id)} strategy={verticalListSortingStrategy}>
        <ol className="ballot" data-testid="ballot">
          {options.map((o, i) => (
            <Row key={o.id} option={o} rank={i + 1} />
          ))}
        </ol>
      </SortableContext>
    </DndContext>
  );
}
