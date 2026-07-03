// Next.js app-router template: remounts per navigation, so every page gets a
// gentle fade-slide entrance (see .page-anim in globals.css).
export default function Template({ children }: { children: React.ReactNode }) {
  return <div className="page-anim">{children}</div>;
}
