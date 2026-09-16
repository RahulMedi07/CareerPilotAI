import { RequireAuth } from '@/components/auth/RequireAuth';
import { Footer } from '@/components/layout/Footer';
import { Header } from '@/components/layout/Header';
import { Sidebar } from '@/components/layout/Sidebar';

/**
 * The application shell.
 *
 * Sidebar and Header live here rather than in the root layout so that any
 * future page outside this group can render without navigation chrome around
 * it. The login and signup pages are exactly that case.
 *
 * The guard wraps the whole group, so every page inside it is covered by one
 * declaration rather than each page remembering to check.
 */
export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <RequireAuth>
      <div className="flex min-h-screen">
        <Sidebar />
        {/* min-w-0: without it this flex child cannot shrink past its widest
            unwrappable child, which pushes the header off narrow screens. */}
        <div className="flex min-h-screen min-w-0 flex-1 flex-col">
          <Header />
          <main className="flex-1 px-4 py-6 sm:px-6">{children}</main>
          <Footer />
        </div>
      </div>
    </RequireAuth>
  );
}
