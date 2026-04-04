import { useState } from "react";
import { Link, useLocation } from "wouter";
import { 
  LayoutDashboard, 
  FileText, 
  Bell, 
  Settings, 
  Menu, 
  X, 
  Search,
  Plus
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [location] = useLocation();

  const navItems = [
    { icon: LayoutDashboard, label: "Dashboard", href: "/" },
    { icon: FileText, label: "Tracked Cases", href: "/cases" },
    { icon: Bell, label: "Alerts", href: "/alerts" },
    { icon: Settings, label: "Settings", href: "/settings" },
  ];

  return (
    <div className="min-h-screen bg-background font-body text-foreground flex overflow-hidden">
      {/* Mobile Sidebar Overlay */}
      {sidebarOpen && (
        <div 
          className="fixed inset-0 bg-black/20 z-40 lg:hidden backdrop-blur-sm"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside 
        className={cn(
          "fixed lg:static inset-y-0 left-0 z-50 w-64 bg-sidebar border-r border-border transform transition-transform duration-300 ease-in-out lg:transform-none flex flex-col shadow-neumorphic",
          sidebarOpen ? "translate-x-0" : "-translate-x-full"
        )}
      >
        <div className="h-20 flex items-center px-6 border-b border-border">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-background shadow-neumorphic flex items-center justify-center text-primary">
              <img src="/images/logo-icon.png" alt="Logo" className="w-8 h-8 object-contain" />
            </div>
            <span className="font-heading font-bold text-xl text-primary">CourtAlert</span>
          </div>
          <button 
            className="ml-auto lg:hidden text-muted-foreground"
            onClick={() => setSidebarOpen(false)}
          >
            <X size={24} />
          </button>
        </div>

        <div className="p-6">
          <Button className="w-full justify-start gap-2 shadow-neumorphic hover:shadow-neumorphic-inset transition-all duration-300 bg-primary text-primary-foreground hover:bg-primary/90 rounded-xl h-12">
            <Plus size={18} />
            <span>Add New Case</span>
          </Button>
        </div>

        <nav className="flex-1 px-4 space-y-2 overflow-y-auto">
          {navItems.map((item) => {
            const isActive = location === item.href;
            return (
              <Link key={item.href} href={item.href}>
                <div 
                  className={cn(
                    "flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-300 cursor-pointer",
                    isActive 
                      ? "bg-background shadow-neumorphic-inset text-primary font-bold" 
                      : "text-muted-foreground hover:text-foreground hover:bg-background/50"
                  )}
                >
                  <item.icon size={20} />
                  <span>{item.label}</span>
                  {isActive && (
                    <div className="ml-auto w-1.5 h-1.5 rounded-full bg-accent shadow-[0_0_8px_var(--accent)]" />
                  )}
                </div>
              </Link>
            );
          })}
        </nav>

        <div className="p-6 border-t border-border">
          <div className="flex items-center gap-3 p-3 rounded-xl bg-background shadow-neumorphic">
            <div className="w-10 h-10 rounded-full bg-muted flex items-center justify-center text-muted-foreground font-heading font-bold">
              JD
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-bold truncate">John Doe</p>
              <p className="text-xs text-muted-foreground truncate">Advocate</p>
            </div>
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 flex flex-col min-w-0 overflow-hidden bg-background">
        {/* Header */}
        <header className="h-20 flex items-center justify-between px-6 lg:px-10 border-b border-border bg-background/80 backdrop-blur-md sticky top-0 z-30">
          <div className="flex items-center gap-4">
            <button 
              className="lg:hidden p-2 rounded-lg text-muted-foreground hover:bg-muted"
              onClick={() => setSidebarOpen(true)}
            >
              <Menu size={24} />
            </button>
            <h1 className="font-heading text-2xl font-bold text-primary hidden sm:block">
              {navItems.find(i => i.href === location)?.label || "Dashboard"}
            </h1>
          </div>

          <div className="flex items-center gap-4">
            <div className="relative hidden sm:block">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground w-4 h-4" />
              <input 
                type="text" 
                placeholder="Search cases..." 
                className="h-10 pl-10 pr-4 rounded-full bg-background shadow-neumorphic-inset border-none focus:ring-1 focus:ring-primary/20 text-sm w-64 transition-all"
              />
            </div>
            <button className="w-10 h-10 rounded-full bg-background shadow-neumorphic flex items-center justify-center text-muted-foreground hover:text-primary transition-colors relative">
              <Bell size={20} />
              <span className="absolute top-2 right-2 w-2 h-2 bg-destructive rounded-full border-2 border-background" />
            </button>
          </div>
        </header>

        {/* Page Content */}
        <div className="flex-1 overflow-y-auto p-6 lg:p-10 scroll-smooth">
          <div className="max-w-7xl mx-auto animate-in fade-in slide-in-from-bottom-4 duration-500">
            {children}
          </div>
        </div>
      </main>
    </div>
  );
}
