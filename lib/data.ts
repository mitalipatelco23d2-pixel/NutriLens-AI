export type Product = {
  id: string;
  name: string;
  brand: string;
  category: string;
  score: number;
  grade: string;
  verdict: string;
  serving: string;
  calories: number;
  protein: number;
  carbs: number;
  fat: number;
  sugar: number;
  sodium: number;
  ingredients: { name: string; type: "good" | "neutral" | "caution"; note: string }[];
  flags: { title: string; detail: string; level: "high" | "medium" | "low" }[];
  color: string;
};

export const products: Product[] = [
  {
    id: "granola", name: "Almond & Honey Granola", brand: "Nourish Organics", category: "Breakfast cereal",
    score: 78, grade: "B", verdict: "Good fit, with one watch-out", serving: "45 g", calories: 186, protein: 6.8, carbs: 28, fat: 6.4, sugar: 7.2, sodium: 92, color: "#e9b85f",
    ingredients: [
      { name: "Whole grain oats (54%)", type: "good", note: "High-fibre whole grain" },
      { name: "Almonds (12%)", type: "good", note: "Healthy fats and protein" },
      { name: "Honey", type: "caution", note: "An added sugar source" },
      { name: "Rice crisps", type: "neutral", note: "Refined grain, moderate amount" },
      { name: "Sunflower oil", type: "neutral", note: "Unsaturated cooking oil" },
    ],
    flags: [
      { title: "Added sugar", detail: "7.2 g per serving—about 29% of your daily free-sugar goal.", level: "medium" },
      { title: "Good fibre base", detail: "Whole oats are the first ingredient and support satiety.", level: "low" },
    ],
  },
  {
    id: "chips", name: "Classic Salted Potato Chips", brand: "Daily Crunch", category: "Savoury snack",
    score: 34, grade: "D", verdict: "Occasional choice", serving: "30 g", calories: 162, protein: 2.1, carbs: 16, fat: 10.4, sugar: 0.4, sodium: 238, color: "#e66f51",
    ingredients: [
      { name: "Potatoes (66%)", type: "neutral", note: "Main food ingredient" },
      { name: "Palm oil", type: "caution", note: "High in saturated fat" },
      { name: "Iodised salt", type: "caution", note: "High sodium per serving" },
    ],
    flags: [
      { title: "High sodium", detail: "One small serving uses 16% of your daily sodium budget.", level: "high" },
      { title: "Ultra-processed", detail: "Energy dense and easy to overconsume.", level: "medium" },
    ],
  },
  {
    id: "yogurt", name: "Natural Greek Yogurt", brand: "Milky Way", category: "Dairy",
    score: 91, grade: "A", verdict: "Excellent everyday choice", serving: "150 g", calories: 118, protein: 13, carbs: 6.2, fat: 4.1, sugar: 5.8, sodium: 67, color: "#79a8d8",
    ingredients: [
      { name: "Pasteurised milk", type: "good", note: "Complete protein and calcium" },
      { name: "Live cultures", type: "good", note: "Supports gut microbial diversity" },
    ],
    flags: [{ title: "No added sugar", detail: "All listed sugar is naturally occurring lactose.", level: "low" }],
  },
];

export const weeklyNutrition = [
  { day: "Mon", calories: 1820, protein: 72, sugar: 44 },
  { day: "Tue", calories: 2040, protein: 81, sugar: 51 },
  { day: "Wed", calories: 1910, protein: 76, sugar: 39 },
  { day: "Thu", calories: 2150, protein: 86, sugar: 47 },
  { day: "Fri", calories: 1980, protein: 79, sugar: 35 },
  { day: "Sat", calories: 2260, protein: 89, sugar: 58 },
  { day: "Sun", calories: 1875, protein: 74, sugar: 42 },
];

export const pantry = [
  { name: "Greek yogurt", amount: "2 cups", days: 2, status: "Use soon" },
  { name: "Baby spinach", amount: "180 g", days: 3, status: "Fresh" },
  { name: "Brown bread", amount: "8 slices", days: 4, status: "Fresh" },
  { name: "Almond milk", amount: "1 carton", days: 8, status: "Good" },
  { name: "Rolled oats", amount: "620 g", days: 64, status: "Good" },
];

export const recentScans = [products[0], products[2], products[1]];
