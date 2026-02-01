/**
 * Tab exports
 */

export { BaseTab, type TabConfig, type TabContext } from "./BaseTab";
// Re-export dbus for use by tab classes
export { dbus } from "../dbusClient";
export { OverviewTab } from "./OverviewTab";
export { MeetingsTab } from "./MeetingsTab";
export { SprintTab } from "./SprintTab";
export { SkillsTab } from "./SkillsTab";
export { ServicesTab } from "./ServicesTab";
export { CronTab } from "./CronTab";
export { SlackTab } from "./SlackTab";
export { MemoryTab } from "./MemoryTab";
export { SessionsTab } from "./SessionsTab";
export { PersonasTab } from "./PersonasTab";
export { ToolsTab } from "./ToolsTab";
export { CreateTab } from "./CreateTab";
export { InferenceTab } from "./InferenceTab";
export { PerformanceTab } from "./PerformanceTab";
export { SlopTab } from "./SlopTab";
