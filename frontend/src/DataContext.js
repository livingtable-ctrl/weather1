import { createContext } from 'react';

// DataContext — lives in its own file so tabs can import it without
// importing all of App.jsx. App.jsx provides the value (live data from
// useData plus cron state); tabs consume it via useContext.
export const DataContext = createContext(null);
