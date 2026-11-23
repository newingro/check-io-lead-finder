export function SignOutButton({ className, label = "Esci" }: { className?: string; label?: string }) {
  return (
    <form action="/esci" method="post">
      <button type="submit" className={className ?? "text-xs text-slate underline"}>
        {label}
      </button>
    </form>
  );
}
