interface EvidenceItemProps {
  title: string;
  description: string;
}

export function EvidenceItem({ title, description }: EvidenceItemProps) {
  return (
    <li>
      <strong>{title}:</strong> {description}
    </li>
  );
}
