const express = require('express');
const router = express.Router();
const recipeController = require('../controllers/recipeController');

// Get all recipes with pagination and filters
router.get('/', recipeController.getAllRecipes);

// Get recipe by ID
router.get('/:id', recipeController.getRecipeById);

// Import recipe from JSON
router.post('/import', recipeController.importRecipe);

// Delete recipe
router.delete('/:id', recipeController.deleteRecipe);

module.exports = router;