/*
 * Copyright (c) 2019, NVIDIA CORPORATION.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#include <cudf/column/column_factories.hpp>
#include <cudf/strings/strings_column_view.hpp>
#include <cudf/strings/attributes.hpp>

#include <tests/utilities/base_fixture.hpp>
#include <tests/utilities/column_utilities.hpp>
#include <tests/utilities/column_wrapper.hpp>
#include <tests/utilities/type_lists.hpp>
#include "./utilities.h"

#include <vector>
#include <gmock/gmock.h>


struct StringsAttributesTest : public cudf::test::BaseFixture {};

TEST_F(StringsAttributesTest, CodePoints)
{
    std::vector<const char*> h_strings{ "eee", "bb", nullptr, "", "aa", "bbb", "ééé" };
    cudf::test::strings_column_wrapper strings( h_strings.begin(), h_strings.end(),
        thrust::make_transform_iterator( h_strings.begin(), [] (auto str) { return str!=nullptr; }));
    auto strings_view = cudf::strings_column_view(strings);

    {
        auto results = cudf::strings::code_points(strings_view);

        cudf::test::fixed_width_column_wrapper<int32_t> expected{ 101, 101, 101, 98, 98, 97, 97, 98, 98, 98, 50089, 50089, 50089 };
        cudf::test::expect_columns_equal(*results, expected);
    }
}

TEST_F(StringsAttributesTest, ZeroSizeStringsColumn)
{
    cudf::column_view zero_size_strings_column( cudf::data_type{cudf::STRING}, 0, nullptr, nullptr, 0);
    auto strings_view = cudf::strings_column_view(zero_size_strings_column);
    cudf::column_view expected_column( cudf::data_type{cudf::INT32}, 0, nullptr, nullptr, 0);

    auto results = cudf::strings::bytes_counts(strings_view);
    cudf::test::expect_columns_equal(results->view(), expected_column);
    results = cudf::strings::characters_counts(strings_view);
    cudf::test::expect_columns_equal(results->view(), expected_column);
    results = cudf::strings::code_points(strings_view);
    cudf::test::expect_columns_equal(results->view(), expected_column);
}

template <typename T>
class StringsLengthsTest : public StringsAttributesTest {};

using IntegerTypes = cudf::test::Types<int8_t, int16_t, int32_t, int64_t>;
TYPED_TEST_CASE(StringsLengthsTest, IntegerTypes);

TYPED_TEST(StringsLengthsTest, AllIntegerTypes)
{
    std::vector<const char*> h_strings{ "eee", "bb", nullptr, "", "aa", "ééé", " something a bit longer " };
    cudf::test::strings_column_wrapper strings( h_strings.begin(), h_strings.end(),
        thrust::make_transform_iterator( h_strings.begin(), [] (auto str) { return str!=nullptr; }));
    auto strings_view = cudf::strings_column_view(strings);

    auto dtype = cudf::data_type{cudf::experimental::type_to_id<TypeParam>()};
    {
        auto results = cudf::strings::characters_counts(strings_view, dtype);
        std::vector<TypeParam> h_expected{ 3, 2, 0, 0, 2, 3, 24 };
        cudf::test::fixed_width_column_wrapper<TypeParam> expected( h_expected.begin(), h_expected.end(),
            thrust::make_transform_iterator( h_strings.begin(), [] (auto str) { return str!=nullptr; }));

        cudf::test::expect_columns_equal(*results, expected);
    }
    {
        auto results = cudf::strings::bytes_counts(strings_view, dtype);
        std::vector<TypeParam> h_expected{ 3, 2, 0, 0, 2, 6, 24 };
        cudf::test::fixed_width_column_wrapper<TypeParam> expected( h_expected.begin(), h_expected.end(),
            thrust::make_transform_iterator( h_strings.begin(), [] (auto str) { return str!=nullptr; }));

        cudf::test::expect_columns_equal(*results, expected);
    }
}
