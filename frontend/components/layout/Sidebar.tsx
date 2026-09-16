'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  Bookmark,
  Briefcase,
  FileText,
  GraduationCap,
  Home,
  MessageSquare,
  Search,
  Settings,
  Zap,
} from 'lucide-react';

import { cn } from '@/lib/utils';

// Ordered as the work actually happens: upload the CV, read it back, find
// roles for it, prepare, then track. Analyse sits after Find Jobs because it
// needs an advert, and you get one from there.
const NAV_ITEMS = [
  { href: '/', label: 'Home', icon: Home },
  { href: '/my-resume', label: 'My Resume', icon: FileText },
  { href: '/discover-jobs', label: 'Find Jobs', icon: Search },
  { href: '/analyze', label: 'Analyse', icon: Zap },
  { href: '/interview-prep', label: 'Interview Prep', icon: GraduationCap },
  { href: '/assistant', label: 'Assistant', icon: MessageSquare },
  { href: '/my-jobs', label: 'Saved Jobs', icon: Bookmark },
  { href: '/my-applications', label: 'Applications', icon: Briefcase },
  { href: '/settings', label: 'Settings', icon: Settings },
] as const;

export function Sidebar() {
  const pathname = usePathname();

  return (
    // Narrow screens get an icon rail rather than nothing. Hiding the nav
    // below `md` would leave a phone with no way to move between sections at
    // all, and a drawer is more machinery than five links justify.
    <aside className="flex w-14 shrink-0 flex-col border-r bg-sidebar md:w-60">
      <nav className="flex-1 space-y-1 p-2 md:p-3" aria-label="Main">
        {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
          // startsWith, not equality, so a future detail route such as
          // /my-applications/abc123 still lights up its section.
          const active = pathname === href || pathname.startsWith(`${href}/`);

          return (
            <Link
              key={href}
              href={href}
              title={label}
              aria-current={active ? 'page' : undefined}
              className={cn(
                'flex items-center justify-center gap-3 rounded-md px-2 py-2 text-sm font-medium transition-colors md:justify-start md:px-3',
                active
                  ? 'bg-sidebar-accent text-sidebar-accent-foreground'
                  : 'text-sidebar-foreground/70 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground',
              )}
            >
              <Icon className="size-4 shrink-0" aria-hidden />
              <span className="hidden md:inline">{label}</span>
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
