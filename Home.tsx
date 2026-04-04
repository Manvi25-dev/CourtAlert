import { useState } from "react";
import DashboardLayout from "@/components/DashboardLayout";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { 
  BarChart, 
  Bar, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  LineChart,
  Line
} from "recharts";
import { 
  ArrowUpRight, 
  Calendar, 
  CheckCircle2, 
  Clock, 
  AlertTriangle,
  Gavel,
  Plus
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// Mock Data
const stats = [
  { 
    title: "Total Cases", 
    value: "124", 
    change: "+12%", 
    icon: Gavel,
    trend: "up"
  },
  { 
    title: "Upcoming Hearings", 
    value: "8", 
    change: "Next 7 days", 
    icon: Calendar,
    trend: "neutral"
  },
  { 
    title: "Pending Alerts", 
    value: "3", 
    change: "Urgent", 
    icon: AlertTriangle,
    trend: "down",
    alert: true
  },
  { 
    title: "Cases Disposed", 
    value: "42", 
    change: "+5%", 
    icon: CheckCircle2,
    trend: "up"
  },
];

const hearingsData = [
  { day: "Mon", regular: 4, supplementary: 2 },
  { day: "Tue", regular: 3, supplementary: 1 },
  { day: "Wed", regular: 5, supplementary: 3 },
  { day: "Thu", regular: 2, supplementary: 0 },
  { day: "Fri", regular: 6, supplementary: 4 },
  { day: "Sat", regular: 0, supplementary: 0 },
  { day: "Sun", regular: 0, supplementary: 0 },
];

const statusData = [
  { name: "Active", value: 65, color: "var(--chart-1)" },
  { name: "Listed", value: 15, color: "var(--chart-2)" },
  { name: "Disposed", value: 20, color: "var(--chart-3)" },
];

const recentAlerts = [
  {
    id: 1,
    case: "CRL.M.C. 320/2026",
    type: "Hearing Listed",
    date: "19 Jan 2026",
    court: "Court No. 32",
    status: "urgent"
  },
  {
    id: 2,
    case: "CS 1234/2026",
    type: "Order Uploaded",
    date: "18 Jan 2026",
    court: "Court No. 15",
    status: "info"
  },
  {
    id: 3,
    case: "W.P.(C) 5678/2025",
    type: "Date Changed",
    date: "25 Jan 2026",
    court: "Court No. 4",
    status: "warning"
  }
];

export default function Home() {
  return (
    <DashboardLayout>
      {/* Hero Section */}
      <div className="relative rounded-3xl overflow-hidden mb-10 shadow-neumorphic group">
        <div className="absolute inset-0 bg-primary/90 mix-blend-multiply z-10" />
        <img 
          src="/images/hero-background.jpg" 
          alt="Dashboard Hero" 
          className="w-full h-48 object-cover group-hover:scale-105 transition-transform duration-700"
        />
        <div className="absolute inset-0 z-20 flex flex-col justify-center px-8 sm:px-12">
          <h2 className="font-heading text-3xl sm:text-4xl font-bold text-white mb-2">
            Good Morning, Advocate
          </h2>
          <p className="text-blue-100 max-w-xl text-lg font-light">
            You have <span className="font-bold text-accent">8 hearings</span> scheduled for this week. 
            The supplementary list for tomorrow has been updated.
          </p>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 mb-10">
        {stats.map((stat, index) => (
          <div 
            key={index}
            className="bg-background rounded-2xl p-6 shadow-neumorphic hover:shadow-neumorphic-inset transition-all duration-300 group cursor-default"
          >
            <div className="flex justify-between items-start mb-4">
              <div className={cn(
                "p-3 rounded-xl shadow-neumorphic-inset",
                stat.alert ? "text-destructive bg-destructive/5" : "text-primary bg-primary/5"
              )}>
                <stat.icon size={24} />
              </div>
              {stat.trend !== "neutral" && (
                <span className={cn(
                  "flex items-center text-xs font-bold px-2 py-1 rounded-full",
                  stat.trend === "up" ? "text-green-600 bg-green-100" : "text-red-600 bg-red-100"
                )}>
                  {stat.change} <ArrowUpRight size={12} className="ml-1" />
                </span>
              )}
              {stat.trend === "neutral" && (
                <span className="text-xs font-bold text-muted-foreground px-2 py-1 rounded-full bg-muted">
                  {stat.change}
                </span>
              )}
            </div>
            <h3 className="text-muted-foreground text-sm font-medium mb-1">{stat.title}</h3>
            <p className="font-heading text-3xl font-bold text-foreground">{stat.value}</p>
          </div>
        ))}
      </div>

      {/* Main Content Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        
        {/* Charts Section */}
        <div className="lg:col-span-2 space-y-8">
          {/* Hearing Activity Chart */}
          <Card className="border-none shadow-neumorphic bg-background rounded-3xl overflow-hidden">
            <CardHeader>
              <CardTitle className="font-heading text-xl text-primary">Weekly Hearing Activity</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="h-[300px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={hearingsData} margin={{ top: 20, right: 30, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
                    <XAxis 
                      dataKey="day" 
                      axisLine={false} 
                      tickLine={false} 
                      tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }} 
                      dy={10}
                    />
                    <YAxis 
                      axisLine={false} 
                      tickLine={false} 
                      tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }} 
                    />
                    <Tooltip 
                      cursor={{ fill: 'var(--muted)', opacity: 0.2 }}
                      contentStyle={{ 
                        backgroundColor: 'var(--background)', 
                        borderRadius: '12px', 
                        border: 'none', 
                        boxShadow: 'var(--shadow-neumorphic)' 
                      }}
                    />
                    <Bar 
                      dataKey="regular" 
                      name="Regular List" 
                      fill="var(--chart-1)" 
                      radius={[4, 4, 0, 0]} 
                      barSize={20}
                    />
                    <Bar 
                      dataKey="supplementary" 
                      name="Supplementary" 
                      fill="var(--chart-2)" 
                      radius={[4, 4, 0, 0]} 
                      barSize={20}
                    />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>

          {/* Case Status Distribution */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            <Card className="border-none shadow-neumorphic bg-background rounded-3xl">
              <CardHeader>
                <CardTitle className="font-heading text-xl text-primary">Case Status</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="h-[200px] w-full relative">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={statusData}
                        cx="50%"
                        cy="50%"
                        innerRadius={60}
                        outerRadius={80}
                        paddingAngle={5}
                        dataKey="value"
                      >
                        {statusData.map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={entry.color} stroke="none" />
                        ))}
                      </Pie>
                      <Tooltip 
                        contentStyle={{ 
                          backgroundColor: 'var(--background)', 
                          borderRadius: '12px', 
                          border: 'none', 
                          boxShadow: 'var(--shadow-neumorphic)' 
                        }}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                    <div className="text-center">
                      <span className="block text-2xl font-bold font-heading text-primary">124</span>
                      <span className="text-xs text-muted-foreground uppercase tracking-wider">Total</span>
                    </div>
                  </div>
                </div>
                <div className="flex justify-center gap-4 mt-4">
                  {statusData.map((item, index) => (
                    <div key={index} className="flex items-center gap-2">
                      <div className="w-3 h-3 rounded-full" style={{ backgroundColor: item.color }} />
                      <span className="text-xs text-muted-foreground font-medium">{item.name}</span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>

            <Card className="border-none shadow-neumorphic bg-background rounded-3xl flex flex-col justify-center items-center p-6 text-center">
              <div className="w-20 h-20 rounded-full bg-background shadow-neumorphic flex items-center justify-center mb-4 text-accent">
                <Clock size={32} />
              </div>
              <h3 className="font-heading text-xl font-bold text-primary mb-2">Next Hearing</h3>
              <p className="text-2xl font-mono font-medium text-foreground mb-1">19 Jan 2026</p>
              <p className="text-sm text-muted-foreground">CRL.M.C. 320/2026</p>
              <p className="text-xs font-bold text-primary mt-2 bg-primary/10 px-3 py-1 rounded-full">
                Court No. 32
              </p>
            </Card>
          </div>
        </div>

        {/* Right Column: Alerts & Feed */}
        <div className="space-y-8">
          <Card className="border-none shadow-neumorphic bg-background rounded-3xl h-full">
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="font-heading text-xl text-primary">Recent Alerts</CardTitle>
              <Button variant="ghost" size="sm" className="text-xs text-muted-foreground hover:text-primary">
                View All
              </Button>
            </CardHeader>
            <CardContent className="space-y-4 pt-4">
              {recentAlerts.map((alert) => (
                <div 
                  key={alert.id} 
                  className="group p-4 rounded-2xl bg-background shadow-neumorphic-inset hover:shadow-neumorphic transition-all duration-300 border-l-4 border-transparent hover:border-accent cursor-pointer"
                >
                  <div className="flex justify-between items-start mb-2">
                    <span className={cn(
                      "text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full",
                      alert.status === "urgent" ? "bg-destructive/10 text-destructive" :
                      alert.status === "warning" ? "bg-orange-100 text-orange-600" :
                      "bg-blue-100 text-blue-600"
                    )}>
                      {alert.type}
                    </span>
                    <span className="text-xs text-muted-foreground">{alert.date}</span>
                  </div>
                  <h4 className="font-mono text-sm font-bold text-foreground mb-1">{alert.case}</h4>
                  <p className="text-xs text-muted-foreground flex items-center gap-1">
                    <Gavel size={12} /> {alert.court}
                  </p>
                </div>
              ))}

              <div className="pt-4">
                <div className="p-4 rounded-2xl bg-primary/5 border border-primary/10 flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full bg-primary text-primary-foreground flex items-center justify-center shrink-0">
                    <Plus size={16} />
                  </div>
                  <div>
                    <p className="text-sm font-bold text-primary">Add New Case</p>
                    <p className="text-xs text-muted-foreground">Track a new matter</p>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

      </div>
    </DashboardLayout>
  );
}
