const paths = {
  calendar: "M8 2v4m8-4v4M3 10h18M5 4h14a2 2 0 0 1 2 2v14H3V6a2 2 0 0 1 2-2Zm3 10h2m4 0h2m-8 4h2",
  chat: "M20 11a8 8 0 0 1-8 8H5l-3 3V11a9 9 0 0 1 18 0ZM7 9h8m-8 4h5",
  plus: "M12 5v14M5 12h14",
  arrow: "M5 12h14m-6-6 6 6-6 6",
  clock: "M12 8v5l3 2m6-3a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z",
  people: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2m20 0v-2a4 4 0 0 0-3-3.9M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm8-7.9a4 4 0 0 1 0 7.8",
  room: "M4 21V4l12-2v19M2 21h20m-6-15h4v15M11 12h1",
  check: "m5 12 4 4L19 6",
  settings: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Zm0-6v3m0 14v3M2 12h3m14 0h3M5 5l2 2m10 10 2 2M5 19l2-2M17 7l2-2",
  close: "m6 6 12 12M18 6 6 18",
  refresh: "M20 7v5h-5M4 17v-5h5m10-4a8 8 0 0 0-13-3L4 7m16 10-2 2a8 8 0 0 1-13-3",
  shield: "m12 2 8 4v6c0 5-8 10-8 10S4 17 4 12V6l8-4Zm-4 10 3 3 5-6",
  edit: "m16 3 5 5L9 20H4v-5L16 3Zm-2 2 5 5",
  search: "m21 21-5-5m2-6a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z",
};

export default function Icon({ name, size = 20, ...props }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}><path d={paths[name] || paths.calendar} /></svg>;
}
